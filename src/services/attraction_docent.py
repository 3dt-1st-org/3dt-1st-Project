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

_vault_url = os.getenv("KEY_VAULT_URL")
if not _vault_url:
    raise ValueError("❌ .env에 KEY_VAULT_URL이 설정되지 않았습니다.")

_credential = DefaultAzureCredential()
_kv_client = SecretClient(vault_url=_vault_url, credential=_credential)

def _get_secret(name: str) -> str:
    """Key Vault에서 시크릿 값을 가져오는 헬퍼 함수"""
    return _kv_client.get_secret(name).value

# 모든 시크릿 로드
AZURE_OPENAI_KEY = _get_secret("azure-openai-key")
AZURE_OPENAI_ENDPOINT = _get_secret("azure-openai-endpoint")
AZURE_OPENAI_VERSION = _get_secret("azure-openai-version")
AZURE_OPENAI_ATTRACTION_DEPLOYMENT = _get_secret("azure-openai-deployment-name")

AZURE_SPEECH_KEY = _get_secret("azure-speech-key")
AZURE_SPEECH_REGION = _get_secret("azure-speech-region")

BASIC_REVIEW_COUNT = 5

# 경로 설정
DOCENT_OUTPUT_DIR_MP3 = r"C:\Users\EL030\Desktop\dataschool\3dt-1st-Project\3dt-1st-Project\data\docent\mp3"
DOCENT_OUTPUT_DIR_SCRIPTS = r"C:\Users\EL030\Desktop\dataschool\3dt-1st-Project\3dt-1st-Project\data\docent\scripts"

# 출력 디렉토리 없으면 생성
if not os.path.exists(DOCENT_OUTPUT_DIR_MP3):
    os.makedirs(DOCENT_OUTPUT_DIR_MP3, exist_ok=True)
if not os.path.exists(DOCENT_OUTPUT_DIR_SCRIPTS):
    os.makedirs(DOCENT_OUTPUT_DIR_SCRIPTS, exist_ok=True)

# ==============================================================================
# 1. 데이터 추출 함수
# ==============================================================================
def fetch_attraction_data(attraction_name, table="reviews"):
    """모든 DB 정보를 Key Vault의 'lala-db-' 시크릿에서 가져와 연결합니다."""
    conn = psycopg2.connect(
        host=_get_secret("lala-db-host"),
        port=int(_get_secret("lala-db-port")),
        database=_get_secret("lala-db-name"),
        user=_get_secret("lala-db-user"),
        password=_get_secret("lala-db-password"),
        sslmode="require"
    )
    try:
        with conn.cursor() as cursor:
            if table == "reviews":
                # ✅ attraction_details 테이블에서 데이터 조회 (process_attractions.py와 연동)
                query = """
                    SELECT summary_ko, atmosphere_ko, tips_ko 
                    FROM locallink.attraction_details 
                    WHERE attraction_name = %s;
                """
                cursor.execute(query, (attraction_name,))
                row = cursor.fetchone()
                if row:
                    summary_ko, atmosphere_ko, tips_ko = row
                    # 기존 형식과 호환되도록 변환
                    # keywords = atmosphere (분위기를 키워드로 사용)
                    # reviews = [summary, tips] (요약과 팁을 도슨트 컨텍스트로 사용)
                    keywords = atmosphere_ko if atmosphere_ko else "Not available"
                    reviews = [summary_ko, tips_ko] if summary_ko else []
                    return (keywords, reviews)
                return (None, [])
            else:
                query = "SELECT history, overview FROM locallink.attraction_descriptions WHERE attraction_name = %s;"
                cursor.execute(query, (attraction_name,))
                row = cursor.fetchone()
                return row if row else (None, None)
    finally:
        conn.close()
 


def pick_story_reviews(reviews, max_items=5):
    """비하인드/역사성 힌트가 있는 리뷰를 우선 선택합니다."""
    if not reviews:
        return []

    story_keywords = [
        "역사", "유래", "전설", "설화", "옛날", "과거", "조선", "고려", "왕", "비화",
        "숨", "알려지지", "비밀", "소문", "후기", "사연", "전해", "전해진", "스토리"
    ]

    prioritized = [
        review for review in reviews
        if any(keyword in review for keyword in story_keywords)
    ]

    if len(prioritized) >= max_items:
        return prioritized[:max_items]

    used = set(prioritized)
    remaining = [review for review in reviews if review not in used]
    return (prioritized + remaining)[:max_items]

def get_db_and_llm_resources():
    """Key Vault 및 .env에서 리소스를 로드하고 Azure 클라이언트를 생성합니다."""
    # 1. Key Vault에서 비밀 정보 로드
    db_password = _get_secret("lala-db-password")
    azure_api_key = AZURE_OPENAI_KEY
    
    # 2. Azure OpenAI 설정
    endpoint = AZURE_OPENAI_ENDPOINT
    api_version = AZURE_OPENAI_VERSION
    
    azure_client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=azure_api_key,
        api_version=api_version
    )
    
    return azure_client, db_password

# ==============================================================================
# 2. TTS & STT 서비스
# ==============================================================================
def text_to_speech_english(text, output_filename):
    """음성 파일을 생성함과 동시에 스피커로 실시간 재생합니다."""
    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY, 
        region=AZURE_SPEECH_REGION
    )
    speech_config.speech_synthesis_voice_name = "en-US-AvaNeural"
    
    # 1. 파일 저장 설정
    full_path = os.path.join(DOCENT_OUTPUT_DIR_MP3, output_filename)
    file_config = speechsdk.audio.AudioOutputConfig(filename=full_path)
    # 2. 실시간 스피커 출력 설정 (추가)
    speaker_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
    
    # 먼저 스피커로 재생
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=speaker_config)
    print(f"🔊 [LIVE] Playing guide audio...")
    synthesizer.speak_text_async(text).get() # 소리가 끝날 때까지 기다림
    
    # 재생이 끝나면 파일로도 저장 (기록용)
    file_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=file_config)
    file_synthesizer.speak_text_async(text).get()
    print(f"✅ Saved to: {full_path}")

def listen_for_confirmation():
    """사용자의 Yes/No 대답을 인식합니다."""
    speech_config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
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
    azure_client, _db_password = get_db_and_llm_resources()
    deployment_name = AZURE_OPENAI_ATTRACTION_DEPLOYMENT
    
    # 데이터 먼저 로드
    keywords, reviews = fetch_attraction_data(attraction_name, "reviews")
    history, overview = fetch_attraction_data(attraction_name, "history")

    if mode == "basic":
        # 1. 리뷰 데이터가 있는 경우 (가장 이상적인 상황)
        if keywords and reviews:
            context = f"Keywords: {keywords}\nReviews: {' '.join(reviews[:BASIC_REVIEW_COUNT])}"
            sys_msg = f"""
            당신은 'LALA'의 활기차고 센스 있는 수석 도슨트입니다.
            [미션] 방문객의 실제 리뷰를 바탕으로 이 장소의 '살아있는 매력'을 짧고 강렬하게 소개하세요.
            [가이드라인]
            1. 첫인상: "{attraction_name}에 오신 것을 환영합니다!"로 시작해 키워드({keywords})를 활용해 분위기를 정의하세요.
            2. 공감대: "많은 분들이 이곳의 ~한 점을 좋아하시더라고요"라며 실제 방문객의 목소리를 인용하세요.
            3. 현장감: "Take a moment to look around," 등 사용자와 상호작용하는 구어체를 사용하세요.
            4. 분량: 1분 이내(4~5문장). 마지막엔 반드시 "Would you like to hear more interesting stories?"라고 질문하세요.
            """
        # 2. 리뷰는 없지만 상세 정보(Overview)는 있는 경우
        elif overview:
            context = f"Overview: {overview}"
            sys_msg = f"""
            당신은 장소의 가치를 전달하는 '공간 큐레이터'입니다.
            [미션] 리뷰는 부족하지만, 공식 설명 데이터를 바탕으로 장소의 특징을 품격 있게 소개하세요.
            [가이드라인]
            1. 첫인상: "{attraction_name}에 오신 것을 환영합니다!"로 시작하세요.
            2. 설명: 이 장소의 용도나 건축적 특징 등 Overview 데이터의 핵심을 4문장 내외로 쉽게 풀어주세요.
            3. 유도: 마지막엔 반드시 "Would you like to hear a more interesting story about this place?"라고 질문하세요.
            """
        # 3. 정말 아무것도 없는 경우
        else:
            return "I'm sorry, I couldn't find any information about this place."

    else: # mode == "history"
        # Case A: 역사 정보(history)가 있는 경우 - [스토리텔러]
        if history:
            context = f"History: {history}\nOverview: {overview}"
            sys_msg = """
            당신은 역사 속 숨겨진 드라마를 발굴하는 '비하인드 스토리 작가'입니다.
            [가이드라인]
            1. 훅킹: "사실 이곳엔 여러분이 몰랐던 놀라운 이야기가 숨겨져 있습니다."로 시작하세요.
            2. 드라마 구현: 단순 연도 나열 대신, 당시 인물들의 감정이나 결정적 사건을 '인간적인 드라마'로 풀어서 설명하세요.
            3. 비유: "이건 마치 현대의 ~와 비슷하죠" 같은 비유를 한 번 사용하세요.
            4. 분량: 6문장 이내. 여운을 남기며 마무리하세요.
            """

        # Case B: 역사는 없지만 상세 정보(overview)가 있는 경우
        # (단, 앞에서 리뷰를 썼을 때만 overview를 제공하여 중복 방지)
        elif overview and (keywords and reviews):
            context = f"Overview: {overview}"
            sys_msg = """
            당신은 장소의 구조와 용도를 친절히 설명하는 '인포메이션 가이드'입니다.
            [가이드라인]
            1. 상황 안내: "공식적인 역사 기록은 적지만, 대신 이 장소가 가진 특별한 구조와 즐길 거리를 알려드릴게요."라고 시작하세요.
            2. 관전 포인트: Overview 데이터를 바탕으로 꼭 봐야 할 건축적 특징이나 시설의 의미를 짚어주세요.
            3. 분량: 5문장 내외의 다정한 구어체로 작성하세요.
            """

        # Case C: 위 정보는 없거나 이미 소진되었을 때, 추가 리뷰라도 있는 경우
        elif reviews:
            fallback_reviews = pick_story_reviews(reviews[BASIC_REVIEW_COUNT:], max_items=5)
            if fallback_reviews:
                context = f"Additional Insights: {' '.join(fallback_reviews)}"
                sys_msg = """
                당신은 동네 어르신들만 아는 비화를 들려주는 '로컬 가이드'입니다.
                [가이드라인]
                1. 솔직한 고백: "기록된 역사는 없지만, 방문객들 사이에서 입소문 난 이곳만의 특징을 들려드릴게요."라고 시작하세요.
                2. 리뷰 활용: 추가 리뷰 데이터 중 '사람들이 소름 돋았거나 감동한 지점'을 4~6문장으로 설명하세요.
                """
            else:
                return "I've shared all the interesting insights I have for now. Enjoy your stay!"
        
        # Case D: 진짜 아무것도 없는 경우
        else:
            return "I'm sorry, I couldn't find any historical or detailed stories about this place yet."

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
def process_attractions(attraction_list, language="English"):
    """여러 명소에 대해 기본/역사 도슨트를 순차 생성합니다."""
    for target in attraction_list:
        print(f"\n{'='*60}")
        print(f"🎯 Processing: {target}")
        print(f"{'='*60}")
        
        # 기본 가이드 생성
        script = generate_docent_script(target, mode="basic", language=language)
        print(f"📖 Basic Guide: {script[:50]}...")
        
        # 기본 가이드 대본 저장
        basic_script_path = os.path.join(DOCENT_OUTPUT_DIR_SCRIPTS, f"{target}_basic_guide_script.txt")
        with open(basic_script_path, 'w', encoding='utf-8') as f:
            f.write(script)
        
        text_to_speech_english(script, f"{target}_basic_guide.mp3")
        print(script)
        
        # 사용자 대답 듣기
        if listen_for_confirmation():
            print("✅ User said YES. Generating history guide...")
            h_script = generate_docent_script(target, mode="history", language=language)
            
            # 역사 가이드 대본 저장
            history_script_path = os.path.join(DOCENT_OUTPUT_DIR_SCRIPTS, f"{target}_history_guide_script.txt")
            with open(history_script_path, 'w', encoding='utf-8') as f:
                f.write(h_script)
            
            text_to_speech_english(h_script, f"{target}_history_guide.mp3")
            print("🎉 History guide generated")
            print(h_script)
        else:
            print("⏩ User declined.")

if __name__ == "__main__":
    # 테스트용: 한 개 명소만 처리
    target = "수원화성"
    process_attractions([target])