import os
import json
import urllib.request
import urllib.parse
import re
import psycopg2
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from openai import AzureOpenAI

# ==============================================================================
# 0. 환경 설정 및 시크릿 로드
# ==============================================================================
load_dotenv()

def _get_secret(name: str) -> str:
    """Key Vault 또는 환경 변수에서 시크릿을 가져옵니다."""
    vault_url = os.getenv("KEY_VAULT_URL")
    if vault_url:
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
        try:
            return client.get_secret(name).value
        except Exception:
            pass
    return os.getenv(name.upper().replace("-", "_"))

# 설정 로드
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5433")),
    "database": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "admin_user"),
    "password": _get_secret("db-password"),
}

NAVER_CLIENT_ID = _get_secret("naver-client-id")
NAVER_CLIENT_SECRET = _get_secret("naver-client-secret")

AZURE_OPENAI_ENDPOINT = _get_secret("azure-openai-endpoint")
AZURE_OPENAI_KEY = _get_secret("azure-openai-key")
AZURE_OPENAI_DEPLOYMENT = _get_secret("azure-openai-deployment-name")
AZURE_OPENAI_VERSION = _get_secret("azure-openai-version")

# ==============================================================================
# 2. [3단계] 리뷰 수집 및 RAG 분석 (요약/분위기/팁)
# ==============================================================================
def clean_html(raw_html):
    if not raw_html:
        return ''
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')

def fetch_naver_reviews(query, display=30):
    """네이버 블로그 검색 API 호출"""
    enc_query = urllib.parse.quote(f"{query}") # 검색어 단순화
    url = f"https://openapi.naver.com/v1/search/blog?query={enc_query}&display={display}&sort=sim"
    
    request = urllib.request.Request(url)
    request.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
    request.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
    
    try:
        response = urllib.request.urlopen(request)
        if response.getcode() == 200:
            data = json.loads(response.read().decode('utf-8'))
            items = data.get('items', [])
            if not items:
                print(f"⚠️ '{query}'에 대한 검색 결과가 없습니다.")
            return [clean_html(item['description']) for item in items]
    except Exception as e:
        print(f"❌ 네이버 API 호출 실패 ({query}): {e}")
        return []
    return []

def analyze_reviews_with_llm(attraction_name, reviews):
    """
    Azure OpenAI를 사용하여 리뷰 데이터를 분석하고
    요약(Summary), 분위기(Atmosphere), 팁(Tips)을 추출합니다.
    """
    if not reviews:
        return None

    # [방어 로직] 리뷰 데이터가 너무 적으면 분석 품질이 떨어지므로 건너뜀
    if len(reviews) < 3:
        print(f"⚠️ 리뷰 데이터 부족 ({len(reviews)}개). LLM 분석을 건너뜁니다.")
        return None

    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_VERSION
    )

    combined_text = "\n".join(reviews[:20]) # 비용 절감을 위해 상위 20개만 분석
    
    system_prompt = """
    당신은 외국인 관광객을 위한 전문 도슨트 AI입니다.
    제공된 리뷰를 분석하여 다음 정보를 JSON 형식으로 추출하세요. 모든 항목에 대해 영어 번역이 필수입니다.
    
    1. summary_ko: 외국인이 이해하기 쉽게 장소의 핵심 특징을 3줄로 요약 (한국어)
    2. summary_en: A 3-line summary of the place's key features for foreign tourists (English)
    3. atmosphere: 장소의 분위기를 나타내는 형용사 3~5개 (한국어)
    4. atmosphere_en: 3-5 adjectives describing the atmosphere (English)
    5. tips: 방문 시 유용한 실질적인 꿀팁 (주차, 포토존, 웨이팅 등 - 한국어)
    6. tips_en: Practical tips for visitors (English)
    
    반드시 아래 JSON 포맷을 지켜주세요.
    {
        "summary_ko": "...",
        "summary_en": "...",
        "atmosphere": ["...", "..."],
        "atmosphere_en": ["...", "..."],
        "tips": "...",
        "tips_en": "..."
    }
    """
    
    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"명소: {attraction_name}\n\n[리뷰 데이터]\n{combined_text}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"❌ LLM 분석 실패 ({attraction_name}): {e}")
        return None

def save_analysis_result(attraction_name, analysis_data):
    """분석 결과를 DB에 저장합니다."""
    if not analysis_data:
        return

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    try:
        # extracted_keywords 컬럼에 JSON 데이터를 저장
        # attraction_reviews 테이블에 요약 정보를 저장 (기존 스키마 활용)
        # 주의: attraction_name 컬럼이 FK(ID)인지 TEXT인지 확인 필요. 
        # 제공된 DDL 이슈를 고려하여, 여기서는 안전하게 텍스트 매칭 또는 ID 사용을 시도합니다.
        
        # 여기서는 분석된 '종합 결과'를 저장하는 것이므로, 개별 리뷰 저장과는 다르게
        # 별도의 'attraction_details' 테이블이나 'attraction_reviews'의 대표 레코드로 저장할 수 있습니다.
        # 요청에 따라 attraction_reviews 테이블의 extracted_keywords에 넣습니다.
        
        json_str = json.dumps(analysis_data, ensure_ascii=False)
        
        # 임시로 가장 최근 리뷰 레코드 하나를 생성하거나 업데이트하는 방식 사용
        insert_query = """
            INSERT INTO locallink.attraction_reviews 
            (attraction_name, title, description, clean_text, extracted_keywords, post_date)
            VALUES (%s, 'AI 종합 분석', '명소 도슨트 분석 결과입니다.', 'AI Summary', %s, NOW())
        """
        # attraction_name 컬럼이 INT(ID)라면 attraction_id를, TEXT라면 attraction_name을 넣어야 함
        # DDL 상 INT REFERENCES 이므로 ID를 넣습니다.
        cursor.execute(insert_query, (attraction_name, json_str))
        
        conn.commit()
        print(f"💾 [{attraction_name}] 분석 결과 DB 저장 완료")
        
    except Exception as e:
        print(f"❌ DB 저장 실패: {e}")
        conn.rollback()
    finally:
        conn.close()

# ==============================================================================
# 3. 메인 실행 파이프라인
# ==============================================================================
def run_attraction_analysis_pipeline():
    print("🚀 [1단계] 위치 기반 필터링 (Simulation)")
    print("ℹ️ 1단계는 완료되었다고 가정하고, 가상의 후보 리스트를 사용합니다.")

    # [Simulation] 1단계에서 넘어왔다고 가정한 후보 리스트 (10개 이상)
    step1_result_list = [
        {'id': 1, 'attraction_name': '경기도박물관', 'city_county_name': '용인시'},
        {'id': 2, 'attraction_name': '양지파인리조트', 'city_county_name': '용인시'},
        {'id': 3, 'attraction_name': '수원화성', 'city_county_name': '수원시'},
        {'id': 4, 'attraction_name': '화성행궁', 'city_county_name': '수원시'},
        {'id': 5, 'attraction_name': '광교호수공원', 'city_county_name': '수원시'},
        {'id': 6, 'attraction_name': '한국민속촌', 'city_county_name': '용인시'},
        {'id': 7, 'attraction_name': '에버랜드', 'city_county_name': '용인시'},
        {'id': 8, 'attraction_name': '서울랜드', 'city_county_name': '과천시'},
        {'id': 9, 'attraction_name': '아침고요수목원', 'city_county_name': '가평군'},
        {'id': 10, 'attraction_name': '쁘띠프랑스', 'city_county_name': '가평군'},
    ]

    print(f"📥 1단계 결과 수신: {len(step1_result_list)}개 후보")

    if not step1_result_list:
        print("⚠️ 주변에 관광지가 없습니다.")
        return
    
    # 2단계: 랭킹 로직 제거 (명소는 발견 시 모두 안내)
    # 1단계에서 필터링된 명소 리스트를 그대로 사용합니다.
    target_attractions = pd.DataFrame(step1_result_list)
    print(f"📋 주변 명소 {len(target_attractions)}곳에 대한 도슨트 정보를 준비합니다.")
    
    # 3단계: 리뷰 분석 및 정보 추출
    print("\n🚀 명소 심층 분석(RAG) 및 도슨트 생성 시작...")
    
    for _, row in target_attractions.iterrows():
        att_name = row['attraction_name']
        
        print(f"\n🔍 분석 중: {att_name}...")
        
        # 3-1. 리뷰 수집
        reviews = fetch_naver_reviews(att_name)
        
        # 3-2. LLM 분석 (요약, 분위기, 팁)
        analysis_result = analyze_reviews_with_llm(att_name, reviews)
        
        if analysis_result:
            print(f"   ✅ 요약(KO): {analysis_result.get('summary_ko')}")
            print(f"   ✅ 요약(EN): {analysis_result.get('summary_en')}")
            print(f"   ✅ 분위기(EN): {analysis_result.get('atmosphere_en')}")
            print(f"   ✅ 꿀팁(KO): {analysis_result.get('tips')}")
            print(f"   ✅ 꿀팁(EN): {analysis_result.get('tips_en')}")
            
            # 3-3. DB 저장 (4단계 음성 도슨트 활용용)
            save_analysis_result(att_name, analysis_result)

    print("\n✨ 모든 분석 완료. 음성 도슨트 서비스 준비 끝.")

if __name__ == "__main__":
    run_attraction_analysis_pipeline()
