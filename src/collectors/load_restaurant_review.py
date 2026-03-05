import urllib.request
import urllib.parse
import json
import os
import re
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

# ==============================================================================
# 0. Key Vault 및 인프라 설정
# ==============================================================================
load_dotenv()

_vault_url = os.getenv("KEY_VAULT_URL")
if not _vault_url:
    raise ValueError("❌ .env에 KEY_VAULT_URL이 설정되지 않았습니다.")

_credential = DefaultAzureCredential()
_kv_client = SecretClient(vault_url=_vault_url, credential=_credential)

def _get_secret(name: str) -> str:
    return _kv_client.get_secret(name).value

# 모든 시크릿 로드
NAVER_CLIENT_ID     = _get_secret("naver-client-id")
NAVER_CLIENT_SECRET = _get_secret("naver-client-secret")
AZURE_OPENAI_ENDPOINT   = _get_secret("azure-openai-endpoint")
AZURE_OPENAI_KEY        = _get_secret("azure-openai-key")
AZURE_OPENAI_DEPLOYMENT  = _get_secret("azure-openai-deployment-name")
AZURE_OPENAI_VERSION    = _get_secret("azure-openai-version")
EMBEDDING_DEPLOYMENT_NAME = _get_secret("azure-openai-embedding-deployment-name")
EMBEDDING_API_VERSION     = _get_secret("azure-openai-embedding-api-version")

DB_CONFIG = {
    "host": _get_secret("lala-db-host"),
    "port": int(_get_secret("lala-db-port")),
    "database": _get_secret("lala-db-name"),
    "user": _get_secret("lala-db-user"),
    "password": _get_secret("lala-db-password"),
    "sslmode": "require"
}

# ==============================================================================
# 1. 텍스트 정제 함수 (인코딩 에러 방지 포함)
# ==============================================================================
def clean_html_safe(raw_html):
    """HTML 태그 제거 및 유효하지 않은 UTF-8 문자 정제"""
    if not raw_html: return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    cleantext = cleantext.replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&apos;', "'")
    # [핵심] 인코딩 오류 방지를 위해 깨진 바이트 무시 처리
    return cleantext.encode('utf-8', 'ignore').decode('utf-8')

# ==============================================================================
# 2. LLM 및 임베딩 함수
# ==============================================================================
def extract_keywords_with_llm(restaurant_name, clean_reviews_list):
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_VERSION
    )
    combined_reviews = "\n".join(clean_reviews_list)
    
    system_prompt = """
    당신은 맛집 분석 전문가입니다. 제공된 블로그 리뷰들을 읽고 이 식당의 분위기와 맛을 잘 나타내는 
    핵심 형용사 3개와 명사 3개만 추출하십시오. 반드시 아래 JSON 포맷으로 응답하십시오.
    {"adjectives": ["형용사1", "형용사2", "형용사3"], "nouns": ["명사1", "명사2", "명사3"]}
    """
    user_prompt = f"식당명: {restaurant_name}\n\n[리뷰 텍스트]\n{combined_reviews[:3000]}"
    
    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        data = json.loads(response.choices[0].message.content)
        return ", ".join(data.get("adjectives", []) + data.get("nouns", []))
    except Exception as e:
        print(f"   ⚠️ 키워드 추출 에러: {e}")
        return "맛집, 분위기, 추천"

def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    embedding_client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=EMBEDDING_API_VERSION
    )
    try:
        response = embedding_client.embeddings.create(model=EMBEDDING_DEPLOYMENT_NAME, input=texts)
        return [item.embedding for item in response.data]
    except Exception:
        return []


def has_existing_restaurant_reviews(restaurant_name: str) -> bool:
    """이미 적재된 음식점 리뷰가 있는지 확인합니다."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM locallink.restaurant_reviews
            WHERE restaurant_name = %s;
            """,
            (restaurant_name,)
        )
        existing_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return existing_count > 0
    except Exception as e:
        print(f"   ⚠️ 기존 음식점 리뷰 확인 실패(스킵 체크 생략): {e}")
        return False

# ==============================================================================
# 3. 메인 파이프라인
# ==============================================================================
def run_restaurant_pipeline(target_restaurant):
    print(f"🚀 [{target_restaurant}] 리뷰 수집 및 분석 시작...")

    if has_existing_restaurant_reviews(target_restaurant):
        print(f"   ⏭️ [{target_restaurant}] 이미 리뷰 데이터가 적재되어 있어 건너뜁니다.")
        return

    # [STEP 1] 네이버 API 호출
    search_word = urllib.parse.quote(f"{target_restaurant} 후기")
    url = f"https://openapi.naver.com/v1/search/blog?query={search_word}&display=30&sort=sim"
    
    request = urllib.request.Request(url)
    request.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
    request.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
    
    try:
        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read().decode('utf-8'))
            items = data.get('items', [])
    except Exception as e:
        print(f"   ❌ API 에러: {e}")
        return

    # [STEP 2] 데이터 정제
    cleaned_data_list = []
    pure_texts = []
    for item in items:
        c_title = clean_html_safe(item['title'])
        c_desc = clean_html_safe(item['description'])
        formatted_date = datetime.strptime(item['postdate'], '%Y%m%d').strftime('%Y-%m-%d')
        
        cleaned_data_list.append({
            'title': c_title, 'description': c_desc, 
            'post_date': formatted_date, 'post_link': item['link']
        })
        pure_texts.append(c_desc)

    # 키워드 및 임베딩 생성 (Azure OpenAI 사용)
    keywords_str = extract_keywords_with_llm(target_restaurant, pure_texts)
    embeddings = generate_embeddings_batch(pure_texts)

    # [STEP 3] DB 적재
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        insert_query = """
            INSERT INTO locallink.restaurant_reviews 
            (restaurant_name, title, description, post_date, post_link, clean_text, extracted_keywords, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector);
        """
        for data, emb in zip(cleaned_data_list, embeddings):
            emb_str = "[" + ",".join(map(str, emb)) + "]" if emb else None
            # 텍스트 데이터 한 번 더 안전하게 정제해서 입력
            cursor.execute(insert_query, (
                target_restaurant, 
                data['title'].encode('utf-8', 'ignore').decode('utf-8'),
                data['description'].encode('utf-8', 'ignore').decode('utf-8'),
                data['post_date'], data['post_link'],
                data['description'].encode('utf-8', 'ignore').decode('utf-8'),
                keywords_str.encode('utf-8', 'ignore').decode('utf-8'),
                emb_str
            ))
        conn.commit()
        cursor.close()
        conn.close()
        print(f"   ✅ DB 적재 완료: {target_restaurant}")
    except Exception as e:
        print(f"   ❌ DB 에러: {e}")

# ==============================================================================
# 4. 배치 실행 루프 (상위 10개 식당)
# ==============================================================================
if __name__ == "__main__":
    target_list = [
        "무무옥", "로우파이브신풍", "사과당 수원행궁점", "달달한부엌", 
        "위해브투데이", "키프(KIFF)", "사케도로보", "킵댓 행궁점", 
        "누크녹카라멜하우스", "다담"
    ]
    
    for restaurant in target_list:
        run_restaurant_pipeline(restaurant)
    
    print("\n🎉 모든 식당의 리뷰 데이터 축적이 완료되었습니다.")