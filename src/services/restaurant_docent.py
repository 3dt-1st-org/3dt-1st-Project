import os
import psycopg2
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

# ==============================================================================
# 0. 환경 설정 및 리소스 로드
# ==============================================================================
load_dotenv()

def get_db_and_llm_resources():
    """Key Vault에서 정보를 로드하고 Azure OpenAI 클라이언트를 생성합니다."""
    vault_url = os.getenv("KEY_VAULT_URL")
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=vault_url, credential=credential)

    # 1. Key Vault에서 비밀번호 및 API Key 로드
    db_password = kv_client.get_secret("db-password").value
    azure_api_key = os.getenv("AZURE_OPENAI_KEY")
    
    # 2. Azure OpenAI 설정 정보 (.env 기반)
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_version = os.getenv("AZURE_OPENAI_VERSION", "2024-02-15-preview")
    
    # 3. Azure OpenAI 클라이언트 생성
    azure_client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=azure_api_key,
        api_version=api_version
    )
    
    return azure_client, db_password

# ==============================================================================
# 1. RAG: DB에서 TOP 10 식당 데이터 일괄 추출 (기존 로직 유지)
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
                    reviews = " / ".join([row[1][:150] for row in rows])
                    combined_data.append(f"[{name}]\n- Keywords: {keywords}\n- Insights: {reviews}")
        
        return "\n\n".join(combined_data)
    finally:
        conn.close()

# ==============================================================================
# 2. 통합 도슨트 대본 생성 (Azure OpenAI gpt-4o-mini 활성화)
# ==============================================================================
def generate_integrated_docent_script(restaurant_list, language="English"):
    """Azure OpenAI를 사용하여 통합 오디오 가이드 대본을 생성합니다."""
    # 리소스 로드
    azure_client, db_password = get_db_and_llm_resources()
    
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

    try:
        # 배포하신 이름: 'Restaurant-Docent-gpt-4o-mini'
        deployment_name = os.getenv("AZURE_OPENAI_RESTAURANT_DEPLOYMENT")
        
        response = azure_client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        return response.choices[0].message.content
        
    except Exception as e:
        return f"❌ Azure OpenAI 대본 생성 실패: {str(e)}"

def text_to_speech_english(text, output_filename="eng_guide_voice.mp3"):
    """생성된 영어 대본을 고퀄리티 미국식 영어 음성으로 변환합니다."""
    
    # 1. 설정 로드 (.env에 AZURE_SPEECH_KEY, AZURE_SPEECH_REGION 있어야 함)
    speech_config = speechsdk.SpeechConfig(
        subscription=os.getenv("AZURE_SPEECH_KEY"), 
        region=os.getenv("AZURE_SPEECH_REGION")
    )
    
    # 2. 영어 성우 설정 (Ava는 매우 자연스럽고 친절한 목소리입니다)
    # 남성 목소리를 원하시면 "en-US-AndrewNeural"을 사용하세요.
    speech_config.speech_synthesis_voice_name = "en-US-AvaNeural"
    
    # 3. 파일 저장 설정
    audio_config = speechsdk.audio.AudioOutputConfig(filename=output_filename)
    
    # 4. 합성기 생성 및 실행
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, 
        audio_config=audio_config
    )
    
    print(f"🎙️ [TTS] 영어 음성 합성 시작...")
    result = synthesizer.speak_text_async(text).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"✅ 영어 가이드 파일 생성 완료: {output_filename}")
    else:
        print(f"❌ TTS 에러: {result.reason}")
        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"Error Details: {cancellation_details.error_details}")

# ==============================================================================
# 3. 메인 실행 루프 (수정됨)
# ==============================================================================
if __name__ == "__main__":
    top10_list = [
        "무무옥", "로우파이브신풍", "사과당 수원행궁점", "달달한부엌", 
        "위해브투데이", "키프(KIFF)", "사케도로보", "킵댓 행궁점", 
        "누크녹카라멜하우스", "다담"
    ]
    
    # 1. 대본 생성 (반드시 English로 설정)
    print(f"🎙️ [Batch Mode: Azure OpenAI] {len(top10_list)} Restaurants - Generating English Script...")
    final_script = generate_integrated_docent_script(top10_list, language="English")
    
    if "❌" not in final_script:
        print("\n🌟 [ENGLISH DOCENT SCRIPT GENERATED] 🌟\n")
        print(final_script) 
        
        # 2. 음성 파일 생성
        text_to_speech_english(final_script, "haenggung_food_guide_en.mp3")
    else:
        print(final_script)