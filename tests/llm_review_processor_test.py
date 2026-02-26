import os
import json
from openai import AzureOpenAI
from dotenv import load_dotenv

# 프로젝트 루트의 .env 파일에서 환경변수 로드
load_dotenv()

# ==============================================================================
# 1. Azure OpenAI 클라이언트 설정
# ==============================================================================
# Azure Portal > Azure OpenAI 리소스 > [키 및 엔드포인트] 에서 확인 후 .env 파일에 입력
# Azure Portal의 [Azure OpenAI Studio] -> [Deployments]에서 확인 가능합니다.
AZURE_OAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OAI_API_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OAI_API_VERSION = os.getenv("AZURE_OPENAI_VERSION", "2024-02-15-preview") 
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini") # 배포한 모델 이름 (예: gpt-4o-mini)

# AzureOpenAI 클라이언트 객체 생성
client = AzureOpenAI(
    azure_endpoint=AZURE_OAI_ENDPOINT,
    api_key=AZURE_OAI_API_KEY,
    api_version=AZURE_OAI_API_VERSION
)

# ==============================================================================
# 2. 강력한 System Prompt (페르소나 및 출력 제약 조건 설정)
# ==============================================================================
# AI에게 명확한 역할과 제약 사항, 특히 '광고성 문구 배제'를 강력하게 지시합니다.
SYSTEM_PROMPT = """
당신은 외국인 관광객을 위한 한국 로컬 명소 추천 AI 데이터 분석가입니다.
사용자가 제공하는 수많은 블로그 리뷰 텍스트들을 종합적으로 분석하여, 해당 장소의 분위기와 특징을 가장 잘 나타내는 핵심 키워드를 추출해야 합니다.

[작업 지시 사항]
1. 리뷰 텍스트의 전체적인 문맥을 파악하십시오.
2. "협찬", "소정의 원고료", "제공받아" 등 광고성 멘트가 포함된 문장의 내용은 완전히 무시하십시오.
3. 외국인 관광객이 이 장소를 선택할 때 매력적으로 느낄 만한 '형용사' 3개와 '명사' 3개를 추출하십시오.
4. 출력은 반드시 아래의 JSON 포맷으로만 응답해야 합니다. 어떠한 부가 설명도 덧붙이지 마십시오.

[출력 JSON 포맷 예시]
{
  "adjectives": ["고즈넉한", "활기찬", "사진찍기좋은"],
  "nouns": ["야경", "전통건축", "산책로"]
}
"""

# ==============================================================================
# 3. LLM 메타데이터 추출 메인 함수
# ==============================================================================
def extract_keywords_from_reviews(attraction_name, review_list):
    """
    관광지 명칭과 크롤링한 리뷰 리스트를 받아 gpt-4o-mini 모델을 통해 JSON 메타데이터를 추출합니다.
    """
    # 리뷰 리스트를 하나의 커다란 텍스트 청크(Chunk)로 병합합니다.
    # gpt-4o-mini는 128k 토큰의 막대한 컨텍스트 윈도우를 가지므로 수백 개의 리뷰를 한 번에 넣어도 충분합니다.
    combined_reviews = "\n\n---\n\n".join(review_list)
    
    user_prompt = f"""
분석 대상 명소: {attraction_name}

아래는 해당 명소에 대해 네이버 블로그에서 수집한 실제 방문객 리뷰들입니다.
이 리뷰들을 모두 읽고, 앞서 지시한 JSON 포맷에 맞게 핵심 형용사 3개와 명사 3개를 추출해 주십시오.

[리뷰 텍스트 시작]
{combined_reviews}
[리뷰 텍스트 끝]
"""

    print(f"🔄 '{attraction_name}' 리뷰 분석 중... (Azure OpenAI gpt-4o-mini 호출)")

    try:
        # Azure OpenAI Chat Completions API 호출
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            # 핵심 설정: 모델이 무조건 유효한 JSON 문자열만 뱉어내도록 강제합니다. (파싱 에러 방지)
            response_format={ "type": "json_object" },
            temperature=0.3, # 창의성보다는 정확하고 일관된 정보 추출을 위해 온도를 낮춤
            max_tokens=150   # 출력은 짧은 JSON이므로 토큰 수를 제한하여 비용을 더욱 최소화
        )
        
        # 응답받은 JSON 문자열을 파이썬 딕셔너리로 변환
        result_json_str = response.choices[0].message.content
        result_data = json.loads(result_json_str)
        
        return result_data

    except Exception as e:
        print(f"❌ API 호출 중 에러 발생: {e}")
        return None

# ==============================================================================
# 4. 테스트 실행부 (로컬 검증용 Mock Data)
# ==============================================================================
if __name__ == "__main__":
    
    # 네이버 API에서 수집하여 리스트 형태로 만들었다고 가정한 텍스트 청크 샘플
    mock_reviews_gyeongbokgung = [
        "외국인 친구랑 다녀왔는데 야간 개장 조명이 너무 예뻐서 사진을 백 장은 찍은 것 같아요. 고즈넉한 분위기가 최고입니다.",
        "근정전 스케일에 압도당했습니다. 한복 대여해서 입고 가니까 인생샷 건지기 딱 좋네요. 주말이라 사람은 좀 많았어요.",
        "이 글은 업체로부터 소정의 원고료를 제공받아 작성되었습니다. 하지만 뷰가 좋고 커피가 맛있습니다.", # 광고성 데이터 (AI가 무시해야 함)
        "한국의 역사가 깊게 스며있는 전통 건축물이 멋져요. 산책로를 따라 걷다 보면 마음이 편안해지는 힐링 스팟입니다."
    ]
    
    attraction = "경복궁 근정전"
    
    # 함수 실행
    extracted_data = extract_keywords_from_reviews(attraction, mock_reviews_gyeongbokgung)
    
    if extracted_data:
        print("\n✅ [AI 추출 성공] 완벽한 JSON 형태의 메타데이터가 생성되었습니다!")
        print(json.dumps(extracted_data, ensure_ascii=False, indent=2))
        
        print("\n💡 [활용 방안]")
        print(f"추출된 형용사: {', '.join(extracted_data.get('adjectives', []))}")
        print(f"추출된 명사: {', '.join(extracted_data.get('nouns', []))}")
        print("-> 이 데이터를 PostgreSQL 'reviews_vector' 테이블의 'llm_summary' 컬럼이나 'tags' 배열에 바로 적재할 수 있습니다.")