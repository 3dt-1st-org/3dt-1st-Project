import urllib.request
import urllib.parse
import json
import os
import re
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
from openai import AzureOpenAI

# ==============================================================================
# 0. Key Vault에서 시크릿 로드
# ==============================================================================
load_dotenv()  # KEY_VAULT_URL을 .env에서 읽기 위해 유지

from config.vault_manager import vault

# 네이버 API 키
NAVER_CLIENT_ID     = vault.get_secret("naver-client-id")
NAVER_CLIENT_SECRET = vault.get_secret("naver-client-secret")

# Azure OpenAI 키
AZURE_OPENAI_ENDPOINT   = vault.get_secret("azure-openai-endpoint")
AZURE_OPENAI_KEY        = vault.get_secret("azure-openai-key")
AZURE_OPENAI_DEPLOYMENT = vault.get_secret("azure-openai-deployment-name")
AZURE_OPENAI_VERSION    = vault.get_secret("azure-openai-version")

# Azure OpenAI 임베딩 모델 설정
EMBEDDING_DEPLOYMENT_NAME = vault.get_secret("azure-openai-embedding-deployment-name")
EMBEDDING_API_VERSION     = vault.get_secret("azure-openai-embedding-api-version")

# PostgreSQL DB 접속 정보
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5433")),
    "database": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "admin_user"),
    "password": vault.get_secret("db-password"),
}

print("✅ Key Vault에서 모든 시크릿을 성공적으로 로드했습니다.")

# ==============================================================================
# 1. 텍스트 정제 함수 (HTML 태그 제거)
# ==============================================================================
def clean_html(raw_html):
    """네이버 API 결과에 포함된 <b>, </b>, &quot; 등의 HTML 태그와 특수문자를 제거합니다."""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    # HTML Entity 처리
    cleantext = cleantext.replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&apos;', "'")
    return cleantext

# ==============================================================================
# 2. LLM 전처리 함수 (Azure OpenAI)
# ==============================================================================
def extract_keywords_with_llm(attraction_name, clean_reviews_list):
    """리뷰 텍스트 전체를 분석하여 핵심 형용사/명사를 JSON으로 추출합니다."""
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,  # ✅ 검증 후 str로 확정
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_VERSION
    )
    
    # 리뷰들을 하나의 텍스트로 결합 (LLM에 한 번에 던지기 위함)
    combined_reviews = "\n".join(clean_reviews_list)
    
    system_prompt = """
    당신은 외국인 관광객을 위한 장소 추천 AI입니다. 제공된 블로그 리뷰들을 읽고, 
    광고성 멘트를 제외한 뒤 이 장소의 분위기를 잘 나타내는 핵심 형용사 3개와 명사 3개만 추출하십시오.
    반드시 아래 JSON 포맷으로 응답해야 합니다.
    {"adjectives": ["형용사1", "형용사2", "형용사3"], "nouns": ["명사1", "명사2", "명사3"]}
    """
    
    user_prompt = f"명소: {attraction_name}\n\n[리뷰 텍스트]\n{combined_reviews}"
    
    print(f"🧠 Azure OpenAI ({AZURE_OPENAI_DEPLOYMENT})로 '{attraction_name}' 키워드 추출 중...")
    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=150
        )
        content = response.choices[0].message.content

        if not content:
            print("❌ LLM 응답이 비어있습니다.")
            return []

        try:
            data = json.loads(content)  # ✅ str 타입 확정
        except json.JSONDecodeError as e:
            print(f"❌ JSON 파싱 오류: {e}")
            print(f"원본 응답: {content}")
            return []

        keywords_str = ", ".join(data.get("adjectives", []) + data.get("nouns", []))
        return keywords_str
    
    except Exception as e:
        print(f"❌ LLM 호출 에러: {e}")
        return ""

# ==============================================================================
# 3. 임베딩 생성 함수 (Azure OpenAI text-embedding-3-small)
# ==============================================================================
def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """텍스트 리스트를 한 번의 API 호출로 일괄 벡터 변환합니다. (비용 최적화)"""
    embedding_client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=EMBEDDING_API_VERSION
    )
    print(f"🔢 {EMBEDDING_DEPLOYMENT_NAME}로 {len(texts)}개 리뷰 임베딩 생성 중...")
    try:
        response = embedding_client.embeddings.create(
            model=EMBEDDING_DEPLOYMENT_NAME,
            input=texts
        )
        embeddings = [item.embedding for item in response.data]
        print(f"✅ 임베딩 생성 완료: {len(embeddings)}개")
        return embeddings
    except Exception as e:
        print(f"❌ 임베딩 생성 에러: {e}")
        return []  # ✅ 빈 리스트 반환 (list[list[float]] 타입 유지)

# ==============================================================================
# 4. 메인 파이프라인 (API 호출 -> 전처리 -> DB Insert)
# ==============================================================================
def run_review_pipeline(target_attraction):
    print("==========================================================")
    print(f"🚀 [{target_attraction}] 리뷰 파이프라인 가동 시작")
    print("==========================================================\n")

    # 검색용으로만 괄호 제거 (예: '연무대(동장대)' → '연무대')
    search_attraction = target_attraction.split('(')[0].strip()
    if search_attraction != target_attraction:
        print(f"🔍 검색어 정규화: '{target_attraction}' → '{search_attraction}'")

    # [STEP 1] 네이버 블로그 API 호출 (최대 100개) - 정규화된 이름으로 검색
    search_word = urllib.parse.quote(f"{search_attraction} 설명")
    url = f"https://openapi.naver.com/v1/search/blog?query={search_word}&display=100&sort=sim"
    
    request = urllib.request.Request(url)
    request.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
    request.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
    
    try:
        response = urllib.request.urlopen(request)
        if response.getcode() != 200:
            print(f"❌ API 에러 발생. 코드: {response.getcode()}")
            return

        raw_data = response.read()
        if raw_data is None:
            print("❌ API 응답 데이터가 없습니다.")
            return

        data = json.loads(raw_data.decode('utf-8'))
        items = data.get('items', [])
        print(f"✅ 네이버 API 호출 성공: {len(items)}개의 리뷰 데이터 확보")
        
    except Exception as e:
        print(f"❌ API 요청 중 오류: {e}")
        return

    # [STEP 2] 데이터 정제 및 LLM 전처리
    cleaned_data_list = []
    pure_texts_for_llm = [] # LLM 분석용 텍스트 리스트
    
    for item in items:
        # HTML 태그 제거
        c_title = clean_html(item['title'])
        c_desc = clean_html(item['description'])
        
        # 날짜 포맷 변환 (20231025 -> 2023-10-25)
        raw_date = item['postdate']
        formatted_date = datetime.strptime(raw_date, '%Y%m%d').strftime('%Y-%m-%d')
        
        # 처리된 데이터 임시 저장
        cleaned_data_list.append({
            'title': c_title,   # HTML 제거된 제목
            'description': c_desc, # HTML 제거된 내용
            'post_date': formatted_date,
            'post_link': item['link'],
            'clean_text': c_desc
        })
        pure_texts_for_llm.append(c_desc)

    # 추출된 전체 텍스트를 LLM에 던져서 핵심 키워드 문자열 받아오기
    # (비용 최적화를 위해 100개 리뷰의 분위기를 종합하여 하나의 대표 키워드 세트를 도출합니다)
    extracted_keywords_str = extract_keywords_with_llm(target_attraction, pure_texts_for_llm)
    print(f"✅ LLM 추출 키워드: [{extracted_keywords_str}]")

    # 각 리뷰의 clean_text를 벡터로 일괄 변환 (API 1회 호출로 전체 처리)
    embeddings = generate_embeddings_batch(pure_texts_for_llm)

    # [STEP 3] PostgreSQL (Docker) DB 적재 (Bulk Insert)
    try:
        print("\n🗄️ 데이터베이스 적재 시작...")
        conn = psycopg2.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            database=DB_CONFIG["database"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"]
        )
        cursor = conn.cursor()

        # Insert 쿼리문 준비 (embedding은 pgvector가 인식하는 '[v1,v2,...]' 문자열로 캐스팅)
        insert_query = """
            INSERT INTO locallink.attraction_reviews 
            (attraction_name, title, description, post_date, post_link, clean_text, extracted_keywords, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector);
        """
        
        insert_count = 0
        for data, embedding in zip(cleaned_data_list, embeddings):
            # 벡터를 pgvector 호환 문자열로 변환 (예: '[0.12, -0.34, ...]')
            embedding_str = "[" + ",".join(map(str, embedding)) + "]" if embedding else None
            cursor.execute(insert_query, (
                target_attraction,          # 원본 명소 이름 (괄호 포함) - DB FK 참조
                data['title'],              # 원본 제목
                data['description'],        # 원본 내용
                data['post_date'],          # 작성일 (DATE 타입 호환)
                data['post_link'],          # 블로그 링크
                data['clean_text'],         # HTML 제거된 텍스트
                extracted_keywords_str,     # LLM이 추출한 대표 키워드
                embedding_str               # 1536차원 임베딩 벡터
            ))
            insert_count += 1
            
        conn.commit() # 트랜잭션 확정
        cursor.close()
        conn.close()
        print(f"✅ DB 적재 완료: {insert_count}개의 리뷰가 'locallink.attraction_reviews' 테이블에 안전하게 저장되었습니다.")
        
    except Exception as e:
        print(f"❌ DB 적재 중 오류 발생: {e}")

# ==============================================================================
# 4. 파이프라인 실행
# ==============================================================================
if __name__ == "__main__":
    # '경복궁' 명소를 대상으로 파이프라인 실행
    run_review_pipeline("수원화성")
