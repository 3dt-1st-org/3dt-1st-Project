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
# 1. RAG: DB에서 해당 명소의 데이터 추출
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
            # 명소 리뷰 테이블 (attraction_reviews)에서 데이터 추출
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
# 2. TTS: 영어 음성 변환 (Azure AI Speech)
# ==============================================================================
def text_to_speech_english(text, output_filename="attraction_guide_en.mp3"):
    """생성된 대본을 영어 음성으로 변환합니다."""
    speech_config = speechsdk.SpeechConfig(
        subscription=os.getenv("AZURE_SPEECH_KEY"), 
        region=os.getenv("AZURE_SPEECH_REGION")
    )
    
    # 명소 가이드에 어울리는 Ava 성우 설정
    speech_config.speech_synthesis_voice_name = "en-US-AvaNeural"
    
    audio_config = speechsdk.audio.AudioOutputConfig(filename=output_filename)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    
    print(f"🎙️ [TTS] 음성 파일 생성 중: {output_filename}")
    result = synthesizer.speak_text_async(text).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"✅ TTS 완료: {output_filename}")
    else:
        print(f"❌ TTS 실패: {result.reason}")

# ==============================================================================
# 3. 명소 도슨트 대본 생성 (Azure OpenAI)
# ==============================================================================
def generate_spoken_docent_script(attraction_name, language="English"):
    """Azure OpenAI(gpt-4o-mini)를 사용하여 명소 가이드 대본을 생성합니다."""
    azure_client, db_password = get_db_and_llm_resources()
    keywords, reviews = fetch_all_reviews_for_rag(attraction_name, db_password)
    
    if not keywords:
        return f"⚠️ {attraction_name}에 대한 데이터가 DB에 없습니다."

    # 리뷰 데이터 결합 (너무 길면 상위 데이터 위주로 조절 가능)
    full_context = "\n---\n".join(reviews[:10]) 

    system_prompt = f"""
    당신은 'LALA Global Guide'입니다. 전문 오디오 도슨트로서 명소의 매력을 생생하게 전달하세요.
    단순한 정보 전달이 아니라, 방문객들이 남긴 리뷰를 바탕으로 '현장의 분위기'를 스토리텔링하세요.

    [대본 작성 원칙]
    1. 말투: 친절하고 전문적인 구어체를 사용하세요. (예: "Look around you", "Did you know?")
    2. 데이터 기반: 키워드({keywords})를 중심으로 리뷰의 생생한 묘사를 포함하세요.
    3. 구성: 시작 인사 - 장소 소개 및 현장 분위기 - 관전 포인트 - 마무리 순으로 구성하세요.
    4. 언어: 반드시 {language}로 작성하세요.
    """

    user_prompt = f"""
    [분석 대상 명소]: {attraction_name}
    [방문객 리뷰 데이터]: 
    {full_context}

    위 데이터를 바탕으로 외국인 관광객을 위한 약 1분 30초 분량의 오디오 도슨트 대본을 작성해줘.
    """

    try:
        # .env에 저장하신 명소용 배포 이름 사용
        deployment_name = os.getenv("AZURE_OPENAI_ATTRACTION_DEPLOYMENT")
        
        response = azure_client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Azure OpenAI 에러: {str(e)}"

# ==============================================================================
# 4. 실행 테스트
# ==============================================================================
if __name__ == "__main__":
    target = "수원화성" # 테스트할 명소 이름
    print(f"⚡ [Azure Mode] {target} 데이터 분석 및 가이드 생성 중...")
    
    # 1. 대본 생성
    script = generate_spoken_docent_script(target, language="English")
    
    if "❌" not in script and "⚠️" not in script:
        print("\n" + "="*70)
        print(f"📖 [AUDIO GUIDE SCRIPT - {target}]")
        print("="*70 + "\n")
        print(script)
        
        # 2. 음성 변환 (TTS)
        audio_file = f"{target}_guide_en.mp3"
        text_to_speech_english(script, audio_file)
    else:
        print(script)