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
# 1. [2단계] 가중치 부여 및 랭킹 도출 (맛집 전용)
# ==============================================================================
def get_ranked_restaurants(candidate_list):
    """
    1단계에서 넘어온 음식점 리스트를 받아
    카드/당근 데이터를 기반으로 가중치를 부여하고 Top 10을 선정합니다.
    
    Args:
        candidate_list (list): [{'id': 1, 'restaurant_name': '...', 'city_county_name': '...'}, ...]
    """
    # 1. [예외 처리] 음식점이 10개 미만일 경우 가중치 로직 건너뛰기
    if len(candidate_list) < 10:
        print(f"ℹ️ 후보군이 10개 미만({len(candidate_list)}개)입니다. 가중치 산정을 건너뛰고 전체를 반환합니다.")
        df = pd.DataFrame(candidate_list)
        df['final_score'] = 0.0
        return df

    conn = psycopg2.connect(**DB_CONFIG)
    
    # 리스트에서 이름 추출 (SQL 조회용)
    names = [item['restaurant_name'] for item in candidate_list]

    query = """
    WITH TargetList AS (
        -- 파이썬 리스트를 SQL 임시 테이블로 변환
        SELECT unnest(%s::text[]) as target_name
    ),
    CardStats AS (
        -- [수정] 지역(city) 및 업종(category)별 카드 매출 규모 집계
        -- gyeonggi_card_spending_stats 테이블의 card_tpbuz_nm_2(중분류) 컬럼 활용
        SELECT city, card_tpbuz_nm_2 as category, SUM(amt) as total_amt
        FROM locallink.gyeonggi_card_spending_stats
        GROUP BY city, card_tpbuz_nm_2
    ),
    -- [당근마켓 데이터 반영]
    -- 실제 테이블(locallink.daangn_place_mentions) 조회
    DaangnStats AS (
        SELECT place_name, category, location, mention_count 
        FROM locallink.daangn_place_mentions
        -- WHERE category = '맛집' -- 필요시 주석 해제
    )
    SELECT 
        r.bizplc_nm as restaurant_name,
        r.sigun_nm as city_county_name,
        COALESCE(c.total_amt, 0) as card_score_raw,
        COALESCE(d.mention_count, 0) as daangn_score_raw
    FROM locallink.gg_restaurant_info r
    JOIN TargetList t ON r.bizplc_nm = t.target_name
    -- [수정] 지역(sigun_nm)과 업종(sanittn_bizcond_nm)이 모두 일치하는 카드 데이터 매칭
    -- card_score_raw: 해당 지역 내 해당 업종의 총 매출액 (업종의 인기도/대세 반영)
    LEFT JOIN CardStats c ON r.sigun_nm = c.city AND r.sanittn_bizcond_nm = c.category
    LEFT JOIN DaangnStats d ON r.bizplc_nm = d.place_name
    """
    
    try:
        # names 리스트를 SQL 파라미터로 전달
        df = pd.read_sql(query, conn, params=(names,))
        
        if df.empty:
            df = pd.DataFrame(candidate_list)
            df['final_score'] = 0.0
            return df

        # 정규화 (Min-Max Scaling: (x - min) / (max - min))
        max_card = df['card_score_raw'].max()
        min_card = df['card_score_raw'].min()
        card_range = max_card - min_card
        df['norm_card'] = (df['card_score_raw'] - min_card) / card_range if card_range > 0 else 0
        
        max_daangn = df['daangn_score_raw'].max()
        min_daangn = df['daangn_score_raw'].min()
        daangn_range = max_daangn - min_daangn
        df['norm_daangn'] = (df['daangn_score_raw'] - min_daangn) / daangn_range if daangn_range > 0 else 0

        # 최종 가중치 적용 (카드 40% + 당근 60%)
        df['final_score'] = (df['norm_card'] * 0.4) + (df['norm_daangn'] * 0.6)
        
        # 랭킹 정렬
        return df.sort_values(by='final_score', ascending=False).head(10)

    except Exception as e:
        print(f"❌ 랭킹 쿼리 실패: {e}")
        # 쿼리 실패 시에도 프로그램이 죽지 않도록 기본 점수 부여 후 반환
        df = pd.DataFrame(candidate_list)
        df['final_score'] = 0.0
        return df
    finally:
        conn.close()

# ==============================================================================
# 2. [3단계] 리뷰 수집 및 RAG 분석 (맛집 특화)
# ==============================================================================
def clean_html(raw_html):
    if not raw_html:
        return ''
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')

def fetch_naver_reviews(query, display=30):
    """네이버 블로그 검색 API 호출"""
    enc_query = urllib.parse.quote(f"{query} 맛집") # 검색어 단순화 및 인코딩
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

def analyze_reviews_with_llm(restaurant_name, reviews):
    """
    Azure OpenAI를 사용하여 리뷰 데이터를 분석하고
    요약, 맛/분위기, 추천 메뉴, 꿀팁을 추출합니다.
    """
    if not reviews:
        return None

    if len(reviews) < 3:
        print(f"⚠️ 리뷰 데이터 부족 ({len(reviews)}개). LLM 분석을 건너뜁니다.")
        return None

    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_VERSION
    )

    combined_text = "\n".join(reviews[:20])
    
    system_prompt = """
    당신은 외국인 관광객을 위한 '한국 맛집 전문 가이드 AI'입니다.
    제공된 리뷰를 분석하여 다음 정보를 JSON 형식으로 추출하세요. 모든 항목에 대해 영어 번역이 필수입니다.
    
    1. summary_ko: 맛집의 특징과 맛을 중심으로 한 3줄 요약 (한국어)
    2. summary_en: A 3-line summary focusing on taste and specialty for foreign tourists (English)
    3. atmosphere: 식당의 분위기를 나타내는 형용사 3~5개 (한국어)
    4. atmosphere_en: 3-5 adjectives describing the atmosphere (English)
    5. tips: 방문 시 유용한 꿀팁 (웨이팅, 주차, 추천 메뉴, 먹는 법 등 - 한국어)
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
                {"role": "user", "content": f"맛집: {restaurant_name}\n\n[리뷰 데이터]\n{combined_text}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"❌ LLM 분석 실패 ({restaurant_name}): {e}")
        return None

def save_analysis_result(restaurant_name, analysis_data):
    """분석 결과를 DB에 저장합니다."""
    if not analysis_data:
        return

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    try:
        json_str = json.dumps(analysis_data, ensure_ascii=False)
        
        # 맛집 리뷰 테이블에 저장 (테이블명이 attraction_reviews와 다를 경우 수정 필요)
        # 여기서는 locallink.restaurant_reviews 테이블을 가정합니다.
        insert_query = """
            INSERT INTO locallink.restaurant_reviews 
            (restaurant_name, title, description, clean_text, extracted_keywords, post_date)
            VALUES (%s, 'AI 맛집 분석', 'Top 10 맛집 분석 결과입니다.', 'AI Summary', %s, NOW())
        """
        cursor.execute(insert_query, (restaurant_name, json_str))
        
        conn.commit()
        print(f"💾 [{restaurant_name}] 분석 결과 DB 저장 완료")
        
    except Exception as e:
        print(f"❌ DB 저장 실패: {e}")
        conn.rollback()
    finally:
        conn.close()

def process_restaurant_analysis(restaurant_name):
    """
    [협업용] 개별 음식점에 대한 리뷰 수집, 분석, 저장을 수행하는 통합 함수입니다.
    메인 파이프라인에서 랭킹 선정 후, 각 음식점에 대해 이 함수를 호출하세요.
    """
    print(f"\n🔍 분석 중: {restaurant_name}...")
    
    reviews = fetch_naver_reviews(restaurant_name)
    analysis_result = analyze_reviews_with_llm(restaurant_name, reviews)
    
    if analysis_result:
        print(f"   ✅ 요약(KO): {analysis_result.get('summary_ko')}")
        print(f"   ✅ 요약(EN): {analysis_result.get('summary_en')}")
        print(f"   ✅ 분위기(EN): {analysis_result.get('atmosphere_en')}")
        print(f"   ✅ 꿀팁(KO): {analysis_result.get('tips')}")
        print(f"   ✅ 꿀팁(EN): {analysis_result.get('tips_en')}")
        save_analysis_result(restaurant_name, analysis_result)

# ==============================================================================
# 3. 메인 실행 파이프라인
# ==============================================================================
def run_ranking_and_analysis_pipeline():
    print("🚀 [1단계] 위치 기반 필터링 (Simulation)")
    print("ℹ️ 1단계는 완료되었다고 가정하고, 가상의 후보 리스트를 사용합니다.")

    # [Simulation] 1단계에서 넘어왔다고 가정한 후보 리스트 (10개 이상)
    step1_result_list = [
        {'id': 1, 'restaurant_name': '가보정', 'city_county_name': '수원시', 'category': '한식'},
        {'id': 2, 'restaurant_name': '본수원갈비', 'city_county_name': '수원시', 'category': '한식'},
        {'id': 3, 'restaurant_name': '유치회관', 'city_county_name': '수원시', 'category': '한식'},
        {'id': 4, 'restaurant_name': '보영만두', 'city_county_name': '수원시', 'category': '분식'},
        {'id': 5, 'restaurant_name': '진미통닭', 'city_county_name': '수원시', 'category': '통닭'},
        {'id': 6, 'restaurant_name': '용성통닭', 'city_county_name': '수원시', 'category': '통닭'},
        {'id': 7, 'restaurant_name': '신라갈비', 'city_county_name': '수원시', 'category': '한식'},
        {'id': 8, 'restaurant_name': '나보나', 'city_county_name': '수원시', 'category': '양식'},
        {'id': 9, 'restaurant_name': '그집쭈꾸미', 'city_county_name': '수원시', 'category': '한식'},
        {'id': 10, 'restaurant_name': '서동진의커피랩', 'city_county_name': '수원시', 'category': '카페'},
    ]
    
    print(f"📥 1단계 결과 수신: {len(step1_result_list)}개 후보")
    
    if not step1_result_list:
        print("⚠️ 주변에 음식점이 없습니다.")
        return
    
    # 1단계 & 2단계: 랭킹 도출
    print("\n⚖️ [2단계] 가중치 부여 및 Top 10 선정")
    ranked_df = get_ranked_restaurants(step1_result_list)
    
    if ranked_df.empty:
        print("⚠️ 랭킹 산출 실패")
        return

    print(ranked_df[['restaurant_name', 'final_score']].head(10))

    # 3단계: 리뷰 분석 및 정보 추출
    print("\n🧠 [3단계] Top 10 리뷰 분석 및 RAG 요약")
    for _, row in ranked_df.iterrows():
        # 모듈화된 함수 호출
        process_restaurant_analysis(row['restaurant_name'])

if __name__ == "__main__":
    run_ranking_and_analysis_pipeline()
