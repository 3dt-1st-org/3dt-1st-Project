import os
import json
import re
import requests
import psycopg2
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from openai import AzureOpenAI
from config.vault_manager import vault

# ==============================================================================
# 0. 환경 설정 및 시크릿 로드
# ==============================================================================
load_dotenv()

_secret_cache = {}
_vault_client = None
_vault_disabled = False

def _get_vault_client():
    global _vault_client, _vault_disabled
    if _vault_disabled: return None
    if _vault_client is not None: return _vault_client
    vault_url = os.getenv("KEY_VAULT_URL")
    if not vault_url:
        _vault_disabled = True
        return None
    try:
        credential = DefaultAzureCredential()
        _vault_client = SecretClient(vault_url=vault_url, credential=credential)
        return _vault_client
    except Exception:
        _vault_disabled = True
        return None

def _get_secret(name: str) -> str:
    global _vault_disabled
    if name in _secret_cache: return _secret_cache[name]
    client = _get_vault_client()
    if client is not None:
        try:
            value = client.get_secret(name).value
            _secret_cache[name] = value
            return value
        except Exception:
            _vault_disabled = True
    env_value = os.getenv(name.upper().replace("-", "_"))
    _secret_cache[name] = env_value
    return env_value

# DB 연결: vault.get_db_dsn() 사용 (vault_manager 통일)

NAVER_CLIENT_ID = _get_secret("naver-client-id")
NAVER_CLIENT_SECRET = _get_secret("naver-client-secret")

AZURE_OPENAI_ENDPOINT = _get_secret("azure-openai-endpoint")
AZURE_OPENAI_KEY = _get_secret("azure-openai-key")
AZURE_OPENAI_DEPLOYMENT = _get_secret("azure-openai-deployment-name")
AZURE_OPENAI_VERSION = _get_secret("azure-openai-version")

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
        if df.empty: return pd.DataFrame(candidate_list).assign(final_score=0.0)

        for col in ['card_score_raw', 'daangn_score_raw']:
            mn, mx = df[col].min(), df[col].max()
            df[f'norm_{col.split("_")[0]}'] = (df[col] - mn) / (mx - mn) if mx > mn else 0

        df['final_score'] = (df['norm_card'] * 0.4) + (df['norm_daangn'] * 0.6)
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
    system_prompt = """당신은 외국인 관광객을 위한 '한국 맛집 전문 가이드 AI'입니다. JSON 형식으로 추출하세요.
    {"summary_ko": "...", "summary_en": "...", "atmosphere": ["..."], "atmosphere_en": ["..."], "tips": "...", "tips_en": "..."}"""
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
    
    # 요약 정보 기반 임베딩 생성
    emb_text = f"{analysis_data['summary_ko']} {analysis_data['tips']}"
    vec = generate_embeddings(emb_text)

    conn = psycopg2.connect(vault.get_db_dsn())
    cursor = conn.cursor()
    try:
        # restaurant_reviews 테이블 구조에 맞게 수정 (임베딩 컬럼 포함 가정)
        query = """
            INSERT INTO locallink.restaurant_reviews 
            (restaurant_name, title, description, clean_text, extracted_keywords, post_date, embedding)
            VALUES (%s, 'AI 맛집 분석', 'AI Summary', 'AI Summary', %s, NOW(), %s)
            ON CONFLICT (restaurant_name) DO UPDATE SET extracted_keywords = EXCLUDED.extracted_keywords, embedding = EXCLUDED.embedding;
        """
        cursor.execute(query, (restaurant_name, json.dumps(analysis_data, ensure_ascii=False), vec))
        conn.commit()
        print(f"💾 [{restaurant_name}] 적재 완료")
    except Exception as e:
        print(f"❌ 저장 실패: {e}"); conn.rollback()
    finally: conn.close()

def has_existing_restaurant_analysis(restaurant_name):
    try:
        conn = psycopg2.connect(vault.get_db_dsn())
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM locallink.restaurant_reviews WHERE restaurant_name = %s", (restaurant_name,))
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