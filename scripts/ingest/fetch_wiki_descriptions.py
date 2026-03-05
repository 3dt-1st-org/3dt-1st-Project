import os
import time
import psycopg2
import requests
from bs4 import BeautifulSoup
import wikipediaapi
from dotenv import load_dotenv

# 1. 환경 변수 로드 (.env 파일에 DB 정보가 있어야 함)
load_dotenv()

# DB 연결 설정
DB_CONFIG = {
    'host': os.getenv("DB_HOST", "localhost"),
    'database': os.getenv("DB_NAME", "postgres"),
    'user': os.getenv("DB_USER", "postgres"),
    'password': os.getenv("DB_PASSWORD"),
    'port': os.getenv("DB_PORT", "5432")
}

# DB 비밀번호 누락 시 명확한 에러 메시지 출력 (안전장치)
if not DB_CONFIG['password']:
    raise ValueError("DB 비밀번호가 설정되지 않았습니다. .env 파일을 생성하고 DB_PASSWORD를 입력해주세요.")

# 2. 위키백과 API 설정 (User-Agent 필수)
wiki = wikipediaapi.Wikipedia(
    user_agent='LocalLinkProject/1.0 (contact@example.com)',
    language='ko'
)

# 3. 커스텀 크롤링 소스 정의 (위키백과 누락/부실 명소용)
CUSTOM_SOURCES = {
    '와우정사': 'https://dh.aks.ac.kr/Edu/wiki/index.php/%EC%99%80%EC%9A%B0%EC%A0%95%EC%82%AC',
    '경기도어린이박물관': 'https://dh.aks.ac.kr/Edu/wiki/index.php/%EA%B2%BD%EA%B8%B0%EB%8F%84_%EC%96%B4%EB%A6%B0%EC%9D%B4_%EB%B0%95%EB%AC%BC%EA%B4%80',
    '농촌테마파크': 'https://www.yongin.go.kr/home/yitour/ytour01/yttour05.jsp'
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def search_wikipedia_title(keyword):
    """페이지를 못 찾았을 때, 검색 API로 정확한 제목을 찾아내는 함수"""
    url = "https://ko.wikipedia.org/w/api.php"
    # 위키백과는 User-Agent 헤더가 없으면 요청을 차단함 (필수)
    headers = {
        'User-Agent': 'LocalLinkProject/1.0 (contact@example.com)'
    }
    params = {
        "action": "query",
        "list": "search",
        "srsearch": keyword,
        "format": "json",
        "srlimit": 1
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if "query" in data and "search" in data["query"] and data["query"]["search"]:
                candidate_title = data["query"]["search"][0]["title"]
                # [엄격한 검증] 검색어와 결과 제목 간의 연관성 체크
                # 공백을 제거하고 비교하여 포함 여부 확인 (예: '와우정사' in '용인 와우정사')
                if keyword.replace(" ", "") in candidate_title.replace(" ", ""):
                    return candidate_title
                else:
                    print(f" -> [검증 실패] 검색어 '{keyword}' != 결과 '{candidate_title}' (유사도 낮음)")
    except Exception:
        pass
    return None

def extract_history_section(page):
    """위키백과 섹션 중 역사/유래 관련 텍스트를 추출하고, 없으면 본문에서 추론"""
    target_keywords = ['역사', '유래', '연혁', '건립', '배경', '변천', '축성', '기원', '발자취']
    
    # 1. 섹션 제목으로 찾기 (재귀 탐색)
    def find_recursive(sections):
        for section in sections:
            for keyword in target_keywords:
                if keyword in section.title:
                    return section.text.strip()
            
            found_text = find_recursive(section.sections)
            if found_text:
                return found_text
        return None

    history_text = find_recursive(page.sections)
    
    # 2. 섹션이 없으면 본문에서 역사 관련 문단 추출 (Fallback)
    if not history_text:
        # 역사적 사실을 나타내는 단어들
        history_clues = ['창건', '건립', '완공', '시대', '세워', '년', '세기', '왕', '조선', '고려']
        paragraphs = page.text.split('\n')
        extracted = []
        for p in paragraphs:
            # 문단이 너무 짧지 않고(20자 이상), 역사 단어가 포함되어 있으면 수집
            if len(p) > 20 and any(clue in p for clue in history_clues):
                extracted.append(p.strip())
                if len(extracted) >= 3: # 너무 많이 가져오지 않도록 3문단까지만
                    break
        
        if extracted:
            history_text = "\n\n".join(extracted)

    return history_text

def crawl_custom_site(url):
    """BeautifulSoup을 사용하여 외부 사이트 본문 크롤링"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code != 200:
            return None, None

        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 텍스트 추출 로직 (사이트별 구조가 다르므로 범용적으로 접근)
        # 1. 불필요한 스크립트/스타일 제거
        for script in soup(["script", "style", "header", "footer", "nav"]):
            script.decompose()
            
        # 2. 사이트별 본문 영역 추정
        content_div = None
        
        # 2-1. 디지털향토문화대전 (AKS) / 위키 계열
        if "aks.ac.kr" in url or "wiki" in url:
            content_div = soup.find(id="mw-content-text") or soup.find(class_="mw-parser-output")
        
        # 2-2. 용인시청 (농촌테마파크 등) - 일반적인 관공서 사이트 구조 (div.contents 등)
        elif "yongin.go.kr" in url:
            content_div = soup.find("div", class_="contents") or soup.find("div", id="contents")
        
        # 2-3. Fallback: 못 찾으면 body 전체
        if not content_div:
            content_div = soup.body

        text = content_div.get_text(separator="\n", strip=True) if content_div else ""
        
        # 3. 개요와 역사 분리
        overview = text[:500] + "..." if len(text) > 500 else text
        history = text  # 전체 내용을 역사/상세 컬럼에 저장하여 RAG에서 활용
        
        # 4. 역사 키워드가 포함된 문단이 있다면 그 부분을 history로 우선시
        history_keywords = ['역사', '유래', '건립', '개관', '조성']
        paragraphs = text.split('\n')
        history_paragraphs = [p for p in paragraphs if any(k in p for k in history_keywords) and len(p) > 30]
        
        if history_paragraphs:
            history = "\n\n".join(history_paragraphs)
            
        return overview, history
    except Exception as e:
        print(f" [Custom Crawl Error] {e}")
        return None, None

def main():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        print("--- 위키백과 데이터 적재 시작 (대상: v_filtered_attractions) ---")

        # 3. 크롤링 대상 가져오기
        # [수정] 평택시 데이터 제외 (city_county_name != '평택시')
        fetch_query = """
            SELECT ga.attraction_name, ad.attraction_name, ad.history
            FROM locallink.gyeonggi_attractions ga
            JOIN locallink.v_filtered_attractions v ON ga.attraction_name = v.attraction_name
            LEFT JOIN locallink.attraction_descriptions ad ON ga.attraction_name = ad.attraction_name
            WHERE ga.city_county_name != '평택시'
        """
        
        cur.execute(fetch_query)
        targets = cur.fetchall()
        
        print(f"총 {len(targets)}개의 명소에 대해 검색을 시작합니다.")

        success_count = 0
        for i, (name, existing_name_in_desc, existing_history) in enumerate(targets, 1):
            # 이미 역사 정보까지 꽉 차 있으면 건너뜀
            if existing_name_in_desc and existing_history:
                # print(f"[{i}/{len(targets)}] {name}: 완료됨 (건너뜀)")
                continue

            # 0. 검색어 정제 (괄호 제거: '수원화성(관광지)' -> '수원화성')
            search_keyword = name.split('(')[0].strip()
            print(f"[{i}/{len(targets)}] 검색 중: {search_keyword} ... ", end='', flush=True)
            
            overview, history, url = None, None, None
            is_success = False

            # [전략 1] Custom Source 확인 (와우정사, 농촌테마파크 등)
            if search_keyword in CUSTOM_SOURCES:
                target_url = CUSTOM_SOURCES[search_keyword]
                if target_url:
                    print(f"(Custom Crawler: {target_url}) ... ", end='', flush=True)
                    overview, history = crawl_custom_site(target_url)
                    if overview:
                        url = target_url
                        is_success = True
                    else:
                        print("[실패] 파싱 데이터 없음 ... ", end='', flush=True)
                else:
                    print("(Custom Source: URL 미지정) ... ", end='', flush=True)
            
            # [전략 2] 위키백과 검색 (Custom 대상이 아니거나 실패 시)
            else:
                page = wiki.page(search_keyword)

                # 2-1. 페이지 없으면 검색 API로 제목 찾기 (엄격 검증 적용됨)
                if not page.exists():
                    corrected_title = search_wikipedia_title(search_keyword)
                    if corrected_title:
                        print(f"(제목 보정: {corrected_title}) ... ", end='', flush=True)
                        page = wiki.page(corrected_title)

                if page.exists():
                    # Overview 보강: 요약이 너무 짧으면(50자 미만) 본문 앞부분을 가져옴
                    overview = page.summary.strip()
                    if len(overview) < 50:
                        overview = page.text[0:1000].strip()
                    else:
                        overview = overview[0:1000]

                    history = extract_history_section(page)
                    url = page.fullurl
                    is_success = True

            # ---------------------------------------------------------
            # DB 저장
            # ---------------------------------------------------------
            if is_success:
                if existing_name_in_desc:
                    # 이미 데이터가 있는데 역사만 없었던 경우 -> UPDATE
                    update_query = """
                        UPDATE locallink.attraction_descriptions
                        SET overview = %s, history = %s, source_url = %s, crawled_at = NOW()
                        WHERE attraction_name = %s
                    """
                    cur.execute(update_query, (overview, history, url, name))
                    print(f"[업데이트] (역사 추가: {'성공' if history else '실패'})")
                else:
                    # 아예 없던 경우 -> INSERT
                    insert_query = """
                        INSERT INTO locallink.attraction_descriptions 
                        (attraction_name, overview, history, source_url)
                        VALUES (%s, %s, %s, %s)
                    """
                    cur.execute(insert_query, (name, overview, history, url))
                    print(f"[신규저장] (역사 섹션: {'있음' if history else '없음'})")
                
                conn.commit()
                success_count += 1
            else:
                print("[실패] 페이지 없음")
            
            # API 부하 방지 (너무 빠르면 차단될 수 있음)
            time.sleep(0.5)

        print(f"--- 작업 완료: {success_count}/{len(targets)} 건 저장됨 ---")

    except Exception as e:
        print(f"\n[에러 발생] {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
