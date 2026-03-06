import os
import psycopg2
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
from config.vault_manager import vault

# ==============================================================================
# 0. 환경 설정 및 리소스 로드
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
AZURE_OPENAI_KEY = _get_secret("azure-openai-key")
AZURE_OPENAI_ENDPOINT = _get_secret("azure-openai-endpoint")
AZURE_OPENAI_VERSION = _get_secret("azure-openai-version")
AZURE_SPEECH_KEY = _get_secret("azure-speech-key")
AZURE_SPEECH_REGION = _get_secret("azure-speech-region")
AZURE_OPENAI_RESTAURANT_DEPLOYMENT = _get_secret("azure-openai-deployment-name")

DOCENT_OUTPUT_DIR_MP3 = r"C:\Users\EL030\Desktop\dataschool\3dt-1st-Project\3dt-1st-Project\data\docent\mp3"
DOCENT_OUTPUT_DIR_SCRIPTS = r"C:\Users\EL030\Desktop\dataschool\3dt-1st-Project\3dt-1st-Project\data\docent\scripts"

# 출력 디렉토리 없으면 생성
if not os.path.exists(DOCENT_OUTPUT_DIR_MP3):
    os.makedirs(DOCENT_OUTPUT_DIR_MP3, exist_ok=True)
if not os.path.exists(DOCENT_OUTPUT_DIR_SCRIPTS):
    os.makedirs(DOCENT_OUTPUT_DIR_SCRIPTS, exist_ok=True)

def get_db_and_llm_resources():
    """Key Vault에서 정보를 로드하고 Azure OpenAI 클라이언트를 생성합니다."""
    # 1. Key Vault에서 비밀번호 및 API Key 로드
    db_password = _get_secret("lala-db-password")
    azure_api_key = AZURE_OPENAI_KEY
    
    # 2. Azure OpenAI 설정 정보 (.env 기반)
    endpoint = AZURE_OPENAI_ENDPOINT
    api_version = AZURE_OPENAI_VERSION
    
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
def fetch_top10_context(restaurant_list):
    """리스트에 담긴 10개 식당의 키워드와 리뷰를 DB에서 가져옵니다."""
    conn = psycopg2.connect(vault.get_db_dsn())
    
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
    azure_client, _db_password = get_db_and_llm_resources()
    
    # 1. DB 컨텍스트 확보
    full_context = fetch_top10_context(restaurant_list)
    
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
        deployment_name = AZURE_OPENAI_RESTAURANT_DEPLOYMENT
        
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
    """생성된 영어 대본을 미국식 영어 음성으로 변환합니다."""
    
    # 1. 설정 로드 (.env에 AZURE_SPEECH_KEY, AZURE_SPEECH_REGION 있어야 함)
    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY, 
        region=AZURE_SPEECH_REGION
    )
    
    # 2. 영어 성우 설정 (Ava는 매우 자연스럽고 친절한 목소리입니다)
    # 남성 목소리를 원하시면 "en-US-AndrewNeural"을 사용하세요.
    speech_config.speech_synthesis_voice_name = "en-US-AvaNeural"
    
    # 3. 파일 저장 설정
    full_path = os.path.join(DOCENT_OUTPUT_DIR_MP3, output_filename)
    file_config = speechsdk.audio.AudioOutputConfig(filename=full_path)
    # 4. 스피커 출력 설정 (실시간 재생)
    speaker_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
    
    # 5. 먼저 스피커로 실시간 재생
    speaker_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, 
        audio_config=speaker_config
    )
    
    print(f"🔊 [LIVE] 가이드 음성 재생 중...")
    result = speaker_synthesizer.speak_text_async(text).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"✅ 음성 재생 완료")
    else:
        print(f"❌ 실시간 재생 실패: {result.reason}")
        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"Error Details: {cancellation_details.error_details}")
    
    # 6. 재생 완료 후 파일로도 저장
    file_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, 
        audio_config=file_config
    )
    
    result = file_synthesizer.speak_text_async(text).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"✅ 가이드 파일 저장 완료: {full_path}")
    else:
        print(f"❌ 파일 저장 실패: {result.reason}")
        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"Error Details: {cancellation_details.error_details}")

# ==============================================================================
# 3. 통합 프로세스 함수 (attraction_docent와 일관성)
# ==============================================================================
def process_restaurants(restaurant_list, language="English"):
    """여러 식당의 통합 도슨트를 생성합니다."""
    print(f"\n📊 [Batch Mode] {len(restaurant_list)}개 식당 처리 중...")
    
    # 1. 대본 생성
    final_script = generate_integrated_docent_script(restaurant_list, language=language)
    
    if "❌" not in final_script:
        print("\n🌟 [DOCENT SCRIPT GENERATED] 🌟\n")
        print(final_script[:200] + "..." if len(final_script) > 200 else final_script)
        
        # 대본을 파일에 저장
        script_filename = f"restaurant_guide_{language.lower()}_script.txt"
        script_path = os.path.join(DOCENT_OUTPUT_DIR_SCRIPTS, script_filename)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(final_script)
        print(f"✅ 대본 저장 완료: {script_path}\n")
        
        # 2. 음성 파일 생성
        output_filename = f"restaurant_guide_{language.lower()}.mp3"
        text_to_speech_english(final_script, output_filename)
    else:
        print(final_script)

# ==============================================================================
# 3. 메인 실행 루프 (테스트용)
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
        text_to_speech_english(final_script, "food_guide_en.mp3")
    else:
        print(final_script)