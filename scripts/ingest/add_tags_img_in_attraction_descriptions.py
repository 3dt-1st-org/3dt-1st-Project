import os
import time
import urllib.parse
import psycopg2
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

# DB 및 Key Vault 설정
_vault_url = os.getenv("KEY_VAULT_URL")
_kv_client = SecretClient(vault_url=_vault_url, credential=DefaultAzureCredential())

def _get_secret(name: str) -> str:
    return _kv_client.get_secret(name).value

DB_CONFIG = {
    "host": _get_secret("lala-db-host"),
    "port": int(_get_secret("lala-db-port")),
    "database": _get_secret("lala-db-name"),
    "user": _get_secret("lala-db-user"),
    "password": _get_secret("lala-db-password"),
    "sslmode": "require"
}

def init_driver():
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--disable-gpu")
    opts.add_argument("window-size=1920x1080")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    driver = init_driver()
    wait = WebDriverWait(driver, 8)

    # 직접 입력 검색이 필요한 항목
    special_targets = ["아쿠아플라넷 광교", "우리꽃 캠핑장(삼막골 관광농원)"]

    try:
        # 0. 컬럼 및 코멘트 보장
        # tags 컬럼 확인
        cur.execute("""
            SELECT count(*) FROM information_schema.columns 
            WHERE table_schema = 'locallink' 
              AND table_name = 'attraction_descriptions' 
              AND column_name = 'tags';
        """)
        if cur.fetchone()[0] == 0:
            cur.execute("ALTER TABLE locallink.attraction_descriptions ADD COLUMN tags TEXT[];")
            cur.execute("COMMENT ON COLUMN locallink.attraction_descriptions.tags IS '경기관광포털 상세 페이지의 해시태그 리스트 (예: #역사, #자연 등)';")
            print("--- [알림] tags 컬럼 및 코멘트 생성 완료 ---")

        # image_urls 컬럼 확인
        cur.execute("""
            SELECT count(*) FROM information_schema.columns 
            WHERE table_schema = 'locallink' 
              AND table_name = 'attraction_descriptions' 
              AND column_name = 'image_urls';
        """)
        if cur.fetchone()[0] == 0:
            cur.execute("ALTER TABLE locallink.attraction_descriptions ADD COLUMN image_urls TEXT;")
            cur.execute("COMMENT ON COLUMN locallink.attraction_descriptions.image_urls IS '경기관광포털에서 추출한 명소 대표 이미지 URL';")
            print("--- [알림] image_urls 컬럼 및 코멘트 생성 완료 ---")
        
        # crawled_at 컬럼 확인 및 추가
        cur.execute("""
            SELECT count(*) FROM information_schema.columns 
            WHERE table_schema = 'locallink' 
              AND table_name = 'attraction_descriptions' 
              AND column_name = 'crawled_at';
        """)
        if cur.fetchone()[0] == 0:
            # TIMESTAMP 타입을 사용하여 날짜와 시간을 모두 기록합니다.
            cur.execute("ALTER TABLE locallink.attraction_descriptions ADD COLUMN crawled_at TIMESTAMP;")
            cur.execute("COMMENT ON COLUMN locallink.attraction_descriptions.crawled_at IS '데이터 보강(태그, 이미지) 작업 수행 일시';")
            print("--- [알림] crawled_at 컬럼 및 코멘트 생성 완료 ---")

        conn.commit()

        # 1. 태그나 이미지가 비어있는 대상만 추출
        #cur.execute("SELECT attraction_name FROM locallink.attraction_descriptions WHERE tags IS NULL OR image_urls IS NULL")
        cur.execute("""
            SELECT attraction_name 
            FROM locallink.attraction_descriptions 
            WHERE tags IS NULL OR cardinality(tags) = 0
        """)
        targets = [row[0] for row in cur.fetchall()]

        print(f"--- [데이터 보강] 총 {len(targets)}건 시작 ---")

        for i, name in enumerate(targets, 1):
            print(f"[{i}/{len(targets)}] {name}", end=' ', flush=True)
            
            # 검색 키워드 정제
            search_kw = name.split('(')[0].split('[')[0].strip()
            if "고택수원광주" in search_kw: search_kw = "수원광주이씨고택"
            if "이대원장군묘" in search_kw: search_kw = "이대원장군묘"
            if "양지파인리조트" in search_kw: search_kw = "양지파인리조트 스키장"

            try:
                # 2. 검색 시도
                if name in special_targets:
                    driver.get("https://ggtour.or.kr/travel-info/tourism-info")
                    inp = wait.until(EC.presence_of_element_located((By.ID, "keyword-input")))
                    inp.clear()
                    inp.send_keys(search_kw)
                    inp.send_keys(Keys.ENTER)
                else:
                    encoded = urllib.parse.quote(search_kw)
                    driver.get(f"https://ggtour.or.kr/travel-info/tourism-info?keyword-input={encoded}")

                # 3. 결과 리스트 확인
                wait.until(EC.presence_of_element_located((By.CLASS_NAME, "txt-wrap")))
                items = driver.find_elements(By.CLASS_NAME, "txt-wrap")
                detail_path = None
                
                clean_target = search_kw.replace(" ", "")
                for item in items:
                    title = item.find_element(By.TAG_NAME, "strong").text.replace(" ", "")
                    if clean_target in title or title in clean_target:
                        detail_path = item.get_attribute("onclick").split("'")[1]
                        break
                
                if detail_path:
                    # 4. 상세 페이지에서 '태그'와 '대표이미지'만 추출
                    driver.get(f"https://ggtour.or.kr{detail_path}")
                    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "detail-tag")))
                    
                    # 태그 추출
                    tag_el = driver.find_elements(By.CSS_SELECTOR, ".detail-tag ul li")
                    tags = [t.text.strip().replace("#", "") for t in tag_el if t.text.strip()]
                    
                    # 대표이미지 추출 (og:image)
                    image_url = None
                    try:
                        og_img = driver.find_element(By.CSS_SELECTOR, "meta[property='og:image']").get_attribute("content")
                        if og_img and "http" in og_img:
                            image_url = og_img
                    except:
                        pass
                    
                    # 5. DB 업데이트
                    final_tags = tags if tags and len(tags) > 0 else None
                    final_image = image_url if image_url else None

                    cur.execute("""
                        UPDATE locallink.attraction_descriptions 
                        SET tags = %s, image_urls = %s, crawled_at = NOW()
                        WHERE attraction_name = %s
                    """, (final_tags, final_image, name))
                    conn.commit()
                    
                    # 이미지 성공 여부 표시
                    tag_count = len(tags) if tags else '0(없음)'
                    has_img = '저장 완료' if image_url else '저장 실패'
                    print(f"-> [성공: 태그 {tag_count}개, 이미지 {has_img}]")
                else:
                    print(f"-> [항목 못찾음]")
                

            except Exception as e:
                print(f"-> [에러: {str(e)[:20]}]")
            
            time.sleep(0.4)

    finally:
        driver.quit()
        cur.close()
        conn.close()
        print("\n--- 보강 작업 완료 ---")

if __name__ == "__main__":
    main()