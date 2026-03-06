import os
import time
import urllib.parse
import psycopg2
import wikipediaapi
from dotenv import load_dotenv

# Selenium 관련 라이브러리
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# 1. 초기 설정 및 환경 변수 로드
load_dotenv()
urllib3_warnings = False # 경고 무시 설정

from config.vault_manager import vault  # noqa: E402

# 2. 위키백과 API 설정
wiki = wikipediaapi.Wikipedia(
    user_agent='LocalLinkProject/1.0 (contact@example.com)',
    language='ko'
)

def extract_history_section(page):
    """위키백과 특정 섹션(역사 등) 추출"""
    target_keywords = ['역사', '유래', '연혁', '건립', '배경', '변천', '축성', '기원', '발자취']
    def find_recursive(sections):
        for section in sections:
            if any(kw in section.title for kw in target_keywords):
                return section.text.strip()
            found = find_recursive(section.sections)
            if found: return found
        return None
    return find_recursive(page.sections)

def init_driver():
    """Selenium 드라이버 초기화 (Headless 모드)"""
    chrome_options = Options()
    chrome_options.add_argument("--headless") # 창 숨김
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("window-size=1920x1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    return driver

def crawl_ggtour_selenium(driver, original_nm):
    """경기관광포털 크롤링 및 데이터 반환"""
    # 괄호 및 특수 표현 제거한 키워드로 검색 (매칭률 향상)
    clean_keyword = original_nm.split('(')[0].split('[')[0].split(' 중 ')[0].strip()
    
    # 중복명 처리 (예: 수원광주이씨고택수원광주이씨고택 -> 수원광주이씨고택)
    if "고택수원광주" in clean_keyword:
        clean_keyword = "수원광주이씨고택"
    
    encoded_nm = urllib.parse.quote(clean_keyword)
    search_url = f"https://ggtour.or.kr/travel-info/tourism-info?area-select=0&keyword-input={encoded_nm}&sort-select=0&sort=RECENTLY"
    
    try:
        driver.get(search_url)
        wait = WebDriverWait(driver, 8) 
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "txt-wrap")))

        items = driver.find_elements(By.CLASS_NAME, "txt-wrap")
        detail_path = None

        # 부분 매칭: 검색 결과 중 일치도가 높은 항목 찾기
        for item in items:
            try:
                web_title = item.find_element(By.TAG_NAME, "strong").text.replace(" ", "")
                clean_kw_normalized = clean_keyword.replace(" ", "")
                
                # 정확히 일치하거나 검색어가 포함되면 선택
                if web_title == clean_kw_normalized or clean_kw_normalized in web_title:
                    detail_path = item.get_attribute("onclick").split("'")[1]
                    break
            except:
                continue
        
        # 부분 매칭 실패 시 첫 번째 결과 사용
        if not detail_path and items:
            try:
                detail_path = items[0].get_attribute("onclick").split("'")[1]
            except:
                return None
        
        if not detail_path:
            return None

        # 상세 페이지 이동
        driver.get(f"https://ggtour.or.kr{detail_path}")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "overview")))

        # 기본 정보 파싱
        overview = driver.find_element(By.CLASS_NAME, "overview").text.strip()
        
        # 홈페이지 URL 추출
        source_url = f"https://ggtour.or.kr{detail_path}" 
        try:
            hp_li = driver.find_element(By.CSS_SELECTOR, "li.website.homePageLi")
            href = hp_li.find_element(By.TAG_NAME, "a").get_attribute("href")
            if href and not href.endswith('-'): 
                source_url = href
        except: pass

        # 추가정보 4종 파싱
        info = {}
        info_lis = driver.find_elements(By.CSS_SELECTOR, ".moreinfo-wrap ul li")
        for li in info_lis:
            try:
                k = li.find_element(By.TAG_NAME, "strong").text.strip()
                v = li.find_element(By.TAG_NAME, "span").text.strip()
                info[k] = v
            except: continue

        return {
            "overview": overview,
            "source_url": source_url,
            "use_time": info.get("이용시간"),
            "closed_days": info.get("휴무일"),
            "parking": info.get("주차시설"),
            "pet_allowed": info.get("반려동물동반가능")
        }
    except:
        return None

def main():
    conn = psycopg2.connect(vault.get_db_dsn())
    cur = conn.cursor()
    driver = init_driver()

    try:
        print("--- [최종 통합] 데이터 보강 프로세스 시작 ---")
        cur.execute("SELECT tourist_nm FROM locallink.tourist_spot_info")
        targets = cur.fetchall()

        for i, (name,) in enumerate(targets, 1):
            if not name: continue
            print(f"[{i}/{len(targets)}] {name} 처리 중...", end=' ', flush=True)

            # 변수 초기화
            history, wiki_url = None, None
            overview, source_url = None, None
            use_time, closed_days, parking, pet_allowed = None, None, None, None

            # 0. DB에서 해당 명소의 overview 확인 - 있으면 SKIP
            cur.execute("SELECT overview FROM locallink.attraction_descriptions WHERE attraction_name = %s;", (name,))
            existing = cur.fetchone()
            
            if existing and existing[0]:  # overview가 이미 존재하면
                print("[이미 적재됨]")
                continue

            # 1. 위키백과 조회
            search_kw = name.split('(')[0].split('[')[0].strip()
            # 중복명 처리
            if "고택수원광주" in search_kw:
                search_kw = "수원광주이씨고택"
            
            try:
                page = wiki.page(search_kw)
                if page.exists():
                    history = extract_history_section(page)
                    wiki_url = page.fullurl
                    print("(Wiki OK)", end=' ')
            except: pass

            # 2. 경기관광포털 크롤링 (무조건 할당 로직)
            gg_data = crawl_ggtour_selenium(driver, name)
            
            if gg_data:
                print("(GGtour OK)", end=' ')
                # [수정 포인트] 역사 정보 유무와 상관없이 overview와 추가정보를 채움
                overview = gg_data['overview']
                source_url = gg_data['source_url'] # 크롤링한 URL을 우선 순위로 설정
                use_time = gg_data['use_time']
                closed_days = gg_data['closed_days']
                parking = gg_data['parking']
                pet_allowed = gg_data['pet_allowed']
            else:
                # 크롤링 실패 시에만 위키 URL을 출처로 사용
                source_url = wiki_url
                print("(GGtour Skip)", end=' ')

            # 3. DB UPSERT (데이터가 하나라도 있으면 실행)
            if history or overview:
                upsert_query = """
                    INSERT INTO locallink.attraction_descriptions 
                    (attraction_name, overview, history, source_url, use_time, closed_days, parking, pet_allowed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (attraction_name) DO UPDATE SET 
                        overview = COALESCE(EXCLUDED.overview, attraction_descriptions.overview),
                        history = COALESCE(EXCLUDED.history, attraction_descriptions.history),
                        source_url = COALESCE(EXCLUDED.source_url, attraction_descriptions.source_url),
                        use_time = EXCLUDED.use_time,
                        closed_days = EXCLUDED.closed_days,
                        parking = EXCLUDED.parking,
                        pet_allowed = EXCLUDED.pet_allowed,
                        crawled_at = NOW()
                """
                cur.execute(upsert_query, (
                    name, overview, history, source_url,
                    use_time, closed_days, parking, pet_allowed
                ))
                conn.commit()
                print("[완료]")
            else:
                print("[데이터 없음]")

            time.sleep(0.3)

    finally:
        driver.quit()
        cur.close()
        conn.close()
        print("\n--- 전체 공정 완료 ---")

if __name__ == "__main__":
    main()