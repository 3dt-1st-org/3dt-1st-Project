import os
import psycopg2
from openai import AzureOpenAI
import azure.cognitiveservices.speech as speechsdk
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

# ==============================================================================
# 0. 환경 설정 및 리소스 로드
# ==============================================================================
load_dotenv()

def get_db_and_llm_resources():
    """Key Vault 및 .env에서 리소스를 로드하고 Azure 클라이언트를 생성합니다."""
    vault_url = os.getenv("KEY_VAULT_URL")
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=vault_url, credential=credential)

    # 1. Key Vault에서 비밀 정보 로드
    db_password = kv_client.get_secret("db-password").value
    azure_api_key = os.getenv("AZURE_OPENAI_KEY")
    
    # 2. Azure OpenAI 설정
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_version = os.getenv("AZURE_OPENAI_VERSION", "2024-02-15-preview")
    
    azure_client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=azure_api_key,
        api_version=api_version
    )
    
    return azure_client, db_password

# ==============================================================================
# 1. 데이터 추출 함수 (중요: 이 함수가 정의되어 있어야 합니다)
# ==============================================================================
def fetch_attraction_data(attraction_name, db_password, table="reviews"):
    """리뷰 데이터 또는 나무위키 상세 데이터를 가져옵니다."""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        database=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "admin_user"),
        password=db_password
    )
    try:
        with conn.cursor() as cursor:
            if table == "reviews":
                # 리뷰 데이터 조회
                query = "SELECT extracted_keywords, clean_text FROM locallink.attraction_reviews WHERE attraction_name = %s;"
                cursor.execute(query, (attraction_name,))
                rows = cursor.fetchall()
                return (rows[0][0], [row[1] for row in rows]) if rows else (None, [])
            else:
                # 나무위키 상세 정보 조회
                query = "SELECT history, overview FROM locallink.attraction_details WHERE attraction_name = %s;"
                cursor.execute(query, (attraction_name,))
                row = cursor.fetchone()
                return row if row else (None, None)
    finally:
        conn.close()

# ==============================================================================
# 2. TTS & STT 서비스
# ==============================================================================
def text_to_speech_english(text, output_filename):
    """음성 파일을 생성함과 동시에 스피커로 실시간 재생합니다."""
    speech_config = speechsdk.SpeechConfig(
        subscription=os.getenv("AZURE_SPEECH_KEY"), 
        region=os.getenv("AZURE_SPEECH_REGION")
    )
    speech_config.speech_synthesis_voice_name = "en-US-AvaNeural"
    
    # 1. 파일 저장 설정
    file_config = speechsdk.audio.AudioOutputConfig(filename=output_filename)
    # 2. 실시간 스피커 출력 설정 (추가)
    speaker_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
    
    # 먼저 스피커로 재생
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=speaker_config)
    print(f"🔊 [LIVE] Playing guide audio...")
    synthesizer.speak_text_async(text).get() # 소리가 끝날 때까지 기다림
    
    # 재생이 끝나면 파일로도 저장 (기록용)
    file_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=file_config)
    file_synthesizer.speak_text_async(text).get()
    print(f"✅ Saved to: {output_filename}")

def listen_for_confirmation():
    """사용자의 Yes/No 대답을 인식합니다."""
    speech_config = speechsdk.SpeechConfig(subscription=os.getenv("AZURE_SPEECH_KEY"), region=os.getenv("AZURE_SPEECH_REGION"))
    speech_config.speech_recognition_language = "en-US"
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config)
    
    print("\n🎙️ [STT] Do you want to hear more? (Say 'Yes'...)")
    result = recognizer.recognize_once_async().get()
    
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        response = result.text.lower()
        return any(word in response for word in ["yes", "sure", "yeah", "okay"])
    return False

# ==============================================================================
# 3. 대본 생성 로직
# ==============================================================================
def generate_docent_script(attraction_name, mode="basic", language="English"):
    azure_client, db_password = get_db_and_llm_resources()
    deployment_name = os.getenv("AZURE_OPENAI_ATTRACTION_DEPLOYMENT")
    
    if mode == "basic":
        keywords, reviews = fetch_attraction_data(attraction_name, db_password, "reviews")
        if not keywords: return "No data found."
        context = f"Keywords: {keywords}\nReviews: {' '.join(reviews[:5])}"
        sys_msg = '''
            당신은 'LALA Global Guide'의 활기차고 친절한 AI 도슨트입니다.
            [작성 원칙]
            1. 분위기 위주: 명소의 분위기, 방문객들이 느낀 감성(Keywords)을 중심으로 짧고 강렬하게 설명하세요.
            2. 현장감 유지: "Take a moment to look around," 또는 "Can you feel the breeze?" 같은 표현으로 사용자와 상호작용하세요.
            3. 분량: 1분 이내(약 4~5문장)로 핵심만 전달하세요.
            4. 유도 질문: 반드시 마지막에 "Do you want to hear more about the history?"라고 구체적으로 흥미를 끌며 물어보세요.
        '''
    else:
        history, overview = fetch_attraction_data(attraction_name, db_password, "history")
        if not history: return "I don't have historical details yet."
        context = f"History: {history}\nOverview: {overview}"
        sys_msg = '''
            당신은 베스트셀러 작가이자 역사 스토리텔러입니다.
            데이터를 바탕으로 깊고 흥미로운 비하인드 스토리를 들려주세요.
            [작성 원칙]
            1. 'Why'에 집중: 단순한 연도나 이름 나열 대신, "왜 이 장소가 만들어졌는지", "여기엔 어떤 인간적인 드라마가 있는지"에 집중하세요.
            2. 반전과 비유: "Believe it or not" 또는 "It's like the 18th-century version of..." 같은 표현을 사용하여 현대적인 감각으로 비유하세요.
            3. 6문장 법칙: 가장 흥미로운 1~2가지 포인트만 골라 최대 6문장 이내로 작성하세요. 정보가 너무 많으면 관광객은 지루해합니다.
            4. 쉬운 설명: 전문 용어는 초등학생도 이해할 수 있을 만큼 쉽게 풀어서 설명하세요.
        '''

    response = azure_client.chat.completions.create(
        model=deployment_name,
        messages=[
            {"role": "system", "content": f"{sys_msg} Response must be in {language}."},
            {"role": "user", "content": f"Place: {attraction_name}\nData: {context}"}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content

# ==============================================================================
# 4. 메인 실행
# ==============================================================================
if __name__ == "__main__":
    target = "수원화성"
    
    # 기본 가이드 생성
    script = generate_docent_script(target, mode="basic")
    print(f"📖 Basic Guide: {script[:50]}...")
    text_to_speech_english(script, "basic_guide.mp3")
    print(script)
    
    # 사용자 대답 듣기
    if listen_for_confirmation():
        print("✅ User said YES. Generating history guide...")
        h_script = generate_docent_script(target, mode="history")
        text_to_speech_english(h_script, "history_guide.mp3")
        print("🎉 History guide generated: history_guide.mp3")
        print(h_script)
    else:
        print("⏩ User declined.")