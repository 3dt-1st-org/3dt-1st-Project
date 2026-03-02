import os
import psycopg2
from groq import Groq  
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

# ==============================================================================
# 0. 환경 설정 및 리소스 로드
# ==============================================================================
load_dotenv()

def get_db_and_llm_resources():
    vault_url = os.getenv("KEY_VAULT_URL")
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=vault_url, credential=credential)

    # Key Vault에서 DB 비밀번호 로드
    db_password = kv_client.get_secret("db-password").value
    
    # --- [기존 Azure OpenAI 설정 (주석 보존)] ---
    # api_key = kv_client.get_secret("azure-openai-key").value
    # endpoint = kv_client.get_secret("azure-openai-endpoint").value
    # azure_client = AzureOpenAI(
    #     azure_endpoint=endpoint,
    #     api_key=api_key,
    #     api_version=os.getenv("AZURE_OPENAI_VERSION", "2024-02-15-preview")
    # )
    
    # --- [현재 활성화: Groq 설정] ---
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise ValueError("❌ .env 파일에 GROQ_API_KEY가 설정되지 않았습니다.")
        
    groq_client = Groq(api_key=groq_api_key)
    
    return groq_client, db_password

# ==============================================================================
# 1. RAG: DB에서 TOP 10 식당 데이터 일괄 추출
# ==============================================================================
def fetch_top10_context(restaurant_list, db_password):
    """리스트에 담긴 10개 식당의 키워드와 리뷰를 DB에서 가져옵니다."""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        database=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "admin_user"),
        password=db_password
    )
    
    combined_data = []
    try:
        with conn.cursor() as cursor:
            for name in restaurant_list:
                # 각 식당별 키워드와 대표 리뷰 2개 추출
                query = """
                    SELECT extracted_keywords, clean_text 
                    FROM locallink.restaurant_reviews 
                    WHERE restaurant_name = %s
                    LIMIT 2;
                """
                cursor.execute(query, (name,))
                rows = cursor.fetchall()
                if rows:
                    keywords = rows[0][0]
                    reviews = " / ".join([row[1][:150] for row in rows]) # 요약본
                    combined_data.append(f"[{name}]\n- Keywords: {keywords}\n- Insights: {reviews}")
        
        return "\n\n".join(combined_data)
    finally:
        conn.close()

# ==============================================================================
# 2. 통합 도슨트 대본 생성 (Azure 주석 & Groq 활성화)
# ==============================================================================
def generate_integrated_docent_script(restaurant_list, language="English"):
    """10개 식당 데이터를 분석하여 Groq으로 통합 오디오 가이드를 생성합니다."""
    groq_client, db_password = get_db_and_llm_resources()
    
    # 1. DB 컨텍스트 확보
    full_context = fetch_top10_context(restaurant_list, db_password)
    
    if not full_context:
        return "⚠️ DB에서 식당 데이터를 찾을 수 없습니다."

    system_prompt = f"""
    당신은 'LALA AI Guide'입니다. 현재 위치 주변 맛집 TOP 10을 소개하는 전문 오디오 도슨트입니다.
    
    [대본 작성 원칙]
    1. 구성: 10개 식당을 단순히 나열하지 말고, 분위기와 메뉴 특성에 따라 자연스럽게 연결(Storytelling)하세요.
    2. 데이터 기반: 분석된 키워드와 리뷰 인사이트를 문장에 녹여내어 생생함을 더하세요.
    3. 말투: 이어폰으로 듣는 상황임을 고려하여 리듬감 있는 '구어체'를 사용하세요.
    4. 언어: 반드시 {language}로 작성하세요.
    """

    user_prompt = f"""
    [TOP 10 맛집 데이터]:
    {full_context}

    위 10개 가게를 모두 포함하여 약 2분 분량의 통합 오디오 가이드 대본을 작성해줘.
    """

    # --- [기존 Azure OpenAI 호출 로직 (주석 보존)] ---
    """
    try:
        deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        # get_db_and_llm_resources에서 azure_client를 반환하도록 수정 후 사용 가능
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
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ Groq 대본 생성 실패: {str(e)}"

# ==============================================================================
# 3. 메인 실행 루프
# ==============================================================================
if __name__ == "__main__":
    top10_list = [
        "무무옥", "로우파이브신풍", "사과당 수원행궁점", "달달한부엌", 
        "위해브투데이", "키프(KIFF)", "사케도로보", "킵댓 행궁점", 
        "누크녹카라멜하우스", "다담"
    ]
    
    print(f"🎙️ [Batch Mode: Groq] {len(top10_list)}개 식당 통합 대본 생성 중...")
    
    final_script = generate_integrated_docent_script(top10_list, language="English")
    
    print("\n" + "="*70)
    print("🌟 [INTEGRATED TOP 10 FOOD GUIDE] 🌟")
    print("="*70 + "\n")
    print(final_script)
    print("\n" + "="*70)