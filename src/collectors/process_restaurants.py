import os
import json
import re
import requests
import psycopg2
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from openai import AzureOpenAI
from config.vault_manager import vault

# ==============================================================================
# 0. 환경 설정 및 시크릿 로드 (vault_manager 통일)
# ==============================================================================
load_dotenv()

# DB 연결: vault.get_db_dsn() 사용
NAVER_CLIENT_ID     = vault.get_secret("naver-client-id")
NAVER_CLIENT_SECRET = vault.get_secret("naver-client-secret")

AZURE_OPENAI_ENDPOINT   = vault.get_secret("azure-openai-endpoint")
AZURE_OPENAI_KEY        = vault.get_secret("azure-openai-key")
AZURE_OPENAI_DEPLOYMENT = vault.get_secret("azure-openai-deployment-name")
AZURE_OPENAI_VERSION    = vault.get_secret("azure-openai-version")

# ==============================================================================
# 1. [2단계] 가중치 부여 및 랭킹 도출 (View 활용 최적화)
# ==============================================================================
def get_ranked_restaurants(candidate_list):
    # if len(candidate_list) < 10:
    #     print(f"ℹ️ 후보군이 10개 미만입니다. 전체를 반환합니다.")
    #     return pd.DataFrame(candidate_list).assign(final_score=0.0)

    conn = psycopg2.connect(vault.get_db_dsn())
    names = [item['restaurant_name'] for item in candidate_list]

    query = """
    WITH TargetList AS (
        SELECT unnest(%s::text[]) as target_name
    ),
    TargetInfo AS (
        SELECT t.target_name as bizplc_nm, r.sigun_nm, r.bizcond_div_nm_info
        FROM TargetList t
        LEFT JOIN locallink.gg_restaurant_info r ON t.target_name = r.bizplc_nm
    )
    SELECT 
        ti.bizplc_nm as restaurant_name,
        ti.sigun_nm as city_county_name,
        COALESCE(c.total_amt, 0) as card_score_raw,
        COALESCE(d.total_mention, 0) as daangn_score_raw
    FROM TargetInfo ti
    LEFT JOIN locallink.v_card_stats_summary c 
           ON ti.sigun_nm = c.city AND ti.bizcond_div_nm_info = c.category
    LEFT JOIN daangn.v_daangn_stats_summary d 
           ON ti.bizplc_nm = d.place_name AND ti.sigun_nm = d.city_name
    """
    
    try:
        df = pd.read_sql(query, conn, params=(names,))

        if df.empty:
            df = pd.DataFrame(candidate_list)
            df['final_score'] = 0.0
            return df

        # --- [추가된 이상치 보정 로직] ---
        # IQR Capping 적용: 너무 높은 매출액 데이터가 전체 랭킹을 왜곡하는 것을 방지
        Q1 = df['card_score_raw'].quantile(0.25)
        Q3 = df['card_score_raw'].quantile(0.75)
        IQR = Q3 - Q1
        upper_bound = Q3 + (1.5 * IQR)
        df['card_score_raw'] = df['card_score_raw'].clip(upper=upper_bound)
        # ------------------------------

        # 정규화 (Min-Max Scaling)
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

        # 랭킹 정렬 및 상위 10개 반환
        return df.sort_values(by='final_score', ascending=False).head(10)
        
    except Exception as e:
        print(f"❌ 랭킹 쿼리 실패: {e}")
        return pd.DataFrame(candidate_list).assign(final_score=0.0)
    finally: conn.close()

# ==============================================================================
# 2. [3단계] 리뷰 수집 및 임베딩/LLM 분석
# ==============================================================================
def clean_html(raw_html):
    if not raw_html: return ''
    text = re.sub(re.compile('<.*?>'), '', raw_html)
    return text.replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')

def generate_embeddings(text):
    """검색 고도화를 위한 임베딩 벡터 생성"""
    client = AzureOpenAI(azure_endpoint=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_KEY, api_version=AZURE_OPENAI_VERSION)
    try:
        # 배포된 모델명 확인 필요 (예: text-embedding-3-small)
        response = client.embeddings.create(input=text, model="text-embedding-3-small")
        return response.data[0].embedding
    except Exception as e:
        print(f"❌ 임베딩 실패: {e}"); return None

def fetch_naver_reviews(query, display=30):
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    params = {"query": f"{query} 맛집", "display": display, "sort": "sim"}
    try:
        response = requests.get("https://openapi.naver.com/v1/search/blog", headers=headers, params=params)
        items = response.json().get('items', [])
        return [clean_html(item['description']) for item in items]
    except Exception as e:
        print(f"❌ 네이버 API 에러: {e}"); return []

def analyze_reviews_with_llm(restaurant_name, reviews):
    if not reviews or len(reviews) < 3: return None
    client = AzureOpenAI(azure_endpoint=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_KEY, api_version=AZURE_OPENAI_VERSION)
    combined_text = "\n".join(reviews[:20])
    system_prompt = """
    당신은 외국인 관광객을 위한 '한국 맛집 전문 가이드 AI'입니다.
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
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"맛집: {restaurant_name}\n\n[리뷰]\n{combined_text}"}],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        return json.loads(response.choices[0].message.content)
    except: return None

def save_analysis_result(restaurant_name, analysis_data):
    if not analysis_data: return
    
    # 프롬프트 결과(JSON)의 핵심 필드를 안전하게 조합
    summary_ko = analysis_data.get("summary_ko", "")
    summary_en = analysis_data.get("summary_en", "")
    tips_ko = analysis_data.get("tips", "")
    tips_en = analysis_data.get("tips_en", "")
    atmosphere_ko = ", ".join(analysis_data.get("atmosphere", []) or [])
    atmosphere_en = ", ".join(analysis_data.get("atmosphere_en", []) or [])

    # 요약/팁 기반 임베딩 텍스트 생성 (한/영 포함)
    emb_text = f"{summary_ko} {summary_en} {tips_ko} {tips_en}".strip()
    vec = generate_embeddings(emb_text)

    conn = psycopg2.connect(vault.get_db_dsn())
    cursor = conn.cursor()
    try:
        # 구조화 컬럼 저장: summary/tips/atmosphere를 개별 컬럼으로 적재
        query = """
            INSERT INTO locallink.restaurant_details
            (restaurant_name, summary_ko, summary_en, atmosphere_ko, atmosphere_en, tips_ko, tips_en, embedding, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (restaurant_name) DO UPDATE
            SET summary_ko = EXCLUDED.summary_ko,
                summary_en = EXCLUDED.summary_en,
                atmosphere_ko = EXCLUDED.atmosphere_ko,
                atmosphere_en = EXCLUDED.atmosphere_en,
                tips_ko = EXCLUDED.tips_ko,
                tips_en = EXCLUDED.tips_en,
                embedding = EXCLUDED.embedding,
                updated_at = NOW();
        """
        cursor.execute(
            query,
            (
                restaurant_name,
                summary_ko,
                summary_en,
                atmosphere_ko,
                atmosphere_en,
                tips_ko,
                tips_en,
                vec,
            ),
        )
        conn.commit()
        print(f"💾 [{restaurant_name}] 적재 완료")
    except Exception as e:
        print(f"❌ 저장 실패: {e}"); conn.rollback()
    finally: conn.close()

def has_existing_restaurant_analysis(restaurant_name):
    try:
        conn = psycopg2.connect(vault.get_db_dsn())
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM locallink.restaurant_details WHERE restaurant_name = %s", (restaurant_name,))
        exists = cursor.fetchone()[0] > 0
        conn.close()
        return exists
    except: return False

def process_restaurant_analysis(restaurant_name):
    if has_existing_restaurant_analysis(restaurant_name):
        print(f"⏭️ [{restaurant_name}] 스킵"); return
        
    print(f"\n🔍 분석 중: {restaurant_name}...")
    reviews = fetch_naver_reviews(restaurant_name)
    result = analyze_reviews_with_llm(restaurant_name, reviews)
    if result: save_analysis_result(restaurant_name, result)

# ==============================================================================
# 3. 실행 파이프라인
# ==============================================================================
def run_ranking_and_analysis_pipeline(external_list):
       
    print(f"📥 {len(external_list)}개 후보 분석 시작")
    ranked_df = get_ranked_restaurants(external_list)
    
    if ranked_df.empty: return

    for _, row in ranked_df.iterrows():
        process_restaurant_analysis(row['restaurant_name'])

if __name__ == "__main__":
    run_ranking_and_analysis_pipeline()