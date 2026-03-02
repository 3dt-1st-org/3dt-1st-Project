import os
import psycopg2
from groq import Groq  
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

# ==============================================================================
# 0. 환경 설정 및 Key Vault 로드
# ==============================================================================
load_dotenv()

def get_db_and_llm_resources():
    vault_url = os.getenv("KEY_VAULT_URL")
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=vault_url, credential=credential)

    # Key Vault에서 시크릿 로드
    db_password = kv_client.get_secret("db-password").value
    
    # --- [기존 Azure OpenAI 설정 (주석 보존)] ---
    # api_key = kv_client.get_secret("azure-openai-key").value
    # endpoint = kv_client.get_secret("azure-openai-endpoint").value
    # azure_client = AzureOpenAI(
    #     azure_endpoint=endpoint,
    #     api_key=api_key,
    #     api_version=os.getenv("AZURE_OPENAI_VERSION", "2024-02-15-preview")
    # )
    
    # --- [테스트용 Groq 설정 (현재 활성화)] ---
    # .env 파일에 GROQ_API_KEY=gsk_... 형태로 키를 넣어주세요.
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise ValueError("❌ .env 파일에 GROQ_API_KEY가 설정되지 않았습니다.")
        
    groq_client = Groq(api_key=groq_api_key)
    
    return groq_client, db_password

# ==============================================================================
# 1. RAG: DB에서 해당 명소의 전체 리뷰 데이터 추출 (기본 로직 유지)
# ==============================================================================
def fetch_all_reviews_for_rag(attraction_name, db_password):
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        database=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "admin_user"),
        password=db_password
    )
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT extracted_keywords, clean_text 
                FROM locallink.attraction_reviews 
                WHERE attraction_name = %s;
            """
            cursor.execute(query, (attraction_name,))
            rows = cursor.fetchall()
            if not rows: return None, []
            keywords = rows[0][0] 
            reviews = [row[1] for row in rows]
            return keywords, reviews
    finally:
        conn.close()

# ==============================================================================
# 2. 고도화된 도슨트 대본 생성 (Azure 주석 & Groq 활성화)
# ==============================================================================
def generate_spoken_docent_script(attraction_name, language="English"):
    """전체 리뷰를 분석하여 Groq(Llama 3)로 오디오 가이드 대본을 생성합니다."""
    groq_client, db_password = get_db_and_llm_resources()
    keywords, reviews = fetch_all_reviews_for_rag(attraction_name, db_password)
    
    if not keywords:
        return f"⚠️ {attraction_name}에 대한 데이터가 DB에 없습니다."

    full_context = "\n---\n".join(reviews)

    system_prompt = f"""
    당신은 대한민국 명소를 소개하는 'LALA' 서비스의 전문 오디오 도슨트 'LALA AI Guide'입니다.
    제공된 실제 리뷰 데이터를 분석하여, 방문객들이 공통적으로 느낀 '진짜 분위기'를 생생하게 전달하세요.

    [대본 작성 원칙]
    1. 말투: 이어폰으로 듣는 상황임을 고려하여 생생한 '구어체'를 사용하세요.
    2. 데이터 기반: 키워드({keywords})를 주제로 삼고, 리뷰 속 구체적인 묘사를 활용하세요.
    3. 언어: 반드시 {language}로 작성하세요.
    """

    user_prompt = f"""
    [분석 대상 명소]: {attraction_name}
    [방문객 전수 리뷰 데이터]: {full_context}
    위 데이터를 바탕으로 약 1분 분량의 오디오 도슨트 대본을 작성해줘.
    """

    # --- [기존 Azure OpenAI 호출 로직 (주석 처리)] ---
    """
    try:
        deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        response = azure_client.chat.completions.create(
            model=deployment_name,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Azure 에러: {str(e)}"
    """

    # --- [현재 활성화: Groq 호출 로직] ---
    try:
        chat_completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.6,
            max_tokens=1500
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"❌ Groq 대본 생성 실패: {str(e)}"

# ==============================================================================
# 3. 로직 테스트
# ==============================================================================
if __name__ == "__main__":
    target = "경복궁"
    print(f"⚡ [테스트 모드: Groq/Llama3] {target} 데이터를 분석 중...")
    
    script = generate_spoken_docent_script(target, language="English")
    
    print("\n" + "="*70)
    print(f"📖 [AUDIO GUIDE SCRIPT - {target}]")
    print("="*70 + "\n")
    print(script)
    print("\n" + "="*70)