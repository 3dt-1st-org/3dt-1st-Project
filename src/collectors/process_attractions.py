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
    "host": _get_secret("lala-db-host"),
    "port": _get_secret("lala-db-port"),
    "database": _get_secret("lala-db-name"),
    "user": _get_secret("lala-db-user"),
    "password": _get_secret("lala-db-password"),
    "sslmode": "require"
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
def clean_and_filter_text(raw_html):
    """HTML 태그 제거 및 명소와 무관한 리뷰(맛집, 카페 등) 필터링"""
    if not raw_html:
        return None
    
    # HTML 태그 제거 및 엔티티 변환
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', raw_html)
    text = text.replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')

    # 제외 키워드 설정 (명소 자체의 정보보다 식도락 비중이 높은 리뷰 제외)
    exclude_keywords = ['맛집', '카페', '식당', '디저트', '메뉴판', '존맛', '내돈내산 맛집']
    if any(kw in text for kw in exclude_keywords):
        return None
    
    return text

def has_existing_analysis(attraction_name):
    """이미 분석 결과가 테이블에 존재하는지 확인 (중복 방지)"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM locallink.attraction_details WHERE attraction_name = %s",
            (attraction_name,)
        )
        exists = cursor.fetchone()[0] > 0
        conn.close()
        return exists
    except Exception as e:
        print(f"⚠️ 중복 체크 중 오류: {e}")
        return False
    
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
            valid_reviews = []
            for item in items:
                cleaned = clean_and_filter_text(item['description'])
                if cleaned:
                    valid_reviews.append(cleaned)
            return valid_reviews
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
    특히 리뷰 내용 중 '어떤 날씨나 계절에 방문하면 가장 좋은지(비 오는 날, 맑은 날, 가을 등)'에 대한 언급이 있다면 tips에 포함하세요.
    
    1. summary_ko: 외국인이 이해하기 쉽게 장소의 핵심 특징을 3줄로 요약 (한국어)
    2. summary_en: A 3-line summary of the place's key features for foreign tourists (English)
    3. atmosphere: 장소의 분위기를 나타내는 형용사 3~5개 (한국어)
    4. atmosphere_en: 3-5 adjectives describing the atmosphere (English)
    5. tips: 방문 시 유용한 실질적인 꿀팁 (주차, 포토존, 웨이팅, 날씨/계절 추천 등 - 한국어)
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

# [추가] 임베딩 생성 함수
def generate_embeddings(text):
    """Azure OpenAI를 사용하여 텍스트의 임베딩 벡터를 생성합니다."""
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_VERSION
    )
    try:
        # 모델명은 실제 배포하신 임베딩 모델명(예: text-embedding-3-small)으로 변경하세요.
        response = client.embeddings.create(
            input=text,
            model="text-embedding-3-small" 
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"❌ 임베딩 생성 실패: {e}")
        return None

def save_analysis_result(attraction_name, analysis_data):
    """분석 결과를 DB에 저장합니다."""
    if not analysis_data:
        return

    # 1. 요약된 텍스트를 바탕으로 임베딩 생성 (OpenAI API 호출)
    summary_text = analysis_data['summary_ko'] + " " + analysis_data['tips']
    embedding_vector = generate_embeddings(summary_text) 

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    try:
        query = """
            INSERT INTO locallink.attraction_details 
            (attraction_name, summary_ko, summary_en, atmosphere_ko, atmosphere_en, tips_ko, tips_en, updated_at, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (attraction_name) DO UPDATE SET
            summary_ko = EXCLUDED.summary_ko,
            summary_en = EXCLUDED.summary_en,
            atmosphere_ko = EXCLUDED.atmosphere_ko,
            atmosphere_en = EXCLUDED.atmosphere_en,
            tips_ko = EXCLUDED.tips_ko,
            tips_en = EXCLUDED.tips_en,
            embedding = EXCLUDED.embedding,
            updated_at = NOW();
        """
        cursor.execute(query, (
            attraction_name,
            analysis_data['summary_ko'],
            analysis_data['summary_en'],
            ", ".join(analysis_data['atmosphere']),
            ", ".join(analysis_data['atmosphere_en']),
            analysis_data['tips'],
            analysis_data['tips_en'],
            embedding_vector 
        ))
        
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
def run_attraction_analysis_pipeline(external_attraction_list):
    print(f"📥 2단계: {len(external_attraction_list)}개 후보 분석 시작")

    if not external_attraction_list:
        print("⚠️ 주변에 관광지가 없습니다.")
        return
    
    # 2단계: 랭킹 로직 제거 (명소는 발견 시 모두 안내)
    # 1단계에서 필터링된 명소 리스트를 그대로 사용합니다.
    target_attractions = pd.DataFrame(external_attraction_list)
    print(f"📋 주변 명소 {len(target_attractions)}곳에 대한 도슨트 정보를 준비합니다.")
    
    # 3단계: 리뷰 분석 및 정보 추출
    print("\n🚀 명소 심층 분석(RAG) 및 도슨트 생성 시작...")
    
    for att in external_attraction_list:
        name = att.get('attraction_name')
        if not name: continue
        
        # 1. 중복 체크
        if has_existing_analysis(name):
            print(f"⏭️ [{name}] 이미 분석된 데이터가 존재하여 건너뜁니다.")
            continue
            
        print(f"\n🔍 분석 중: {name}...")
        
        # 2. 리뷰 수집 및 LLM 분석
        reviews = fetch_naver_reviews(name)
        analysis_result = analyze_reviews_with_llm(name, reviews)
        
        # 3. 결과 저장
        if analysis_result:
            save_analysis_result(name, analysis_result)
            print(f"💾 [{name}] 도슨트 생성 및 DB 저장 완료")

    print("\n✨ 모든 분석 완료.")

if __name__ == "__main__":
    # 다른 코드에서 받아온 예시 리스트
    my_list = [{'attraction_name': '수원화성'}, {'attraction_name': '에버랜드'}]
    run_attraction_analysis_pipeline(my_list)