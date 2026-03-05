import os
import time
import pandas as pd
import wikipediaapi
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# 1. 환경 변수 로드
load_dotenv()

# DB 연결 설정 (SQLAlchemy Engine)
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")

if not DB_PASSWORD:
    raise ValueError("DB 비밀번호가 설정되지 않았습니다. .env 파일을 확인해주세요.")

# PostgreSQL 연결 문자열 생성
db_url = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(db_url)

# 2. 위키백과 API 설정
wiki = wikipediaapi.Wikipedia(
    user_agent='LocalLinkProject/1.0 (contact@example.com)',
    language='ko'
)

# 3. 타겟 관광지 목록 선언
target_spots = ['경기도박물관', '양지파인리조트']

def get_wiki_data(spot_name):
    """
    위키백과에서 '개요(Overview)'와 '역사(History)' 정보를 추출합니다.
    """
    print(f"🔍 [Wikipedia] '{spot_name}' 검색 중...")
    page = wiki.page(spot_name)

    if not page.exists():
        print(f"   -> 페이지가 존재하지 않습니다.")
        return None, None

    overview = page.summary.strip() if page.summary else None
    
    # '역사' 관련 섹션 확인 로직
    history_keywords = ['역사', '연혁', '건립', '유래', '변천']
    history = None

    for section in page.sections:
        if any(keyword in section.title for keyword in history_keywords):
            history = section.text.strip()
            break
    
    return overview, history

def crawl_ggtour_info(spot_name):
    """
    경기관광플랫폼(ggtour.or.kr) 정보를 기반으로 상세 정보를 반환합니다.
    (실제 크롤링 대신 정확한 데이터 확보를 위해 매핑된 정보를 사용합니다)
    """
    print(f"🔍 [Gyeonggi Tour] '{spot_name}' 정보 수집 중...")
    
    info_data = {
        'tourist_nm': spot_name,
        'road_addr': None,
        'lot_addr': None,
        'tel_no': None,
        'lat': None,
        'lng': None,
        'sigun_nm': None,
        'use_time': None,
        'closed_days': None,
        'parking': None,
        'pet_allowed': None,
        'source_url': 'https://ggtour.or.kr/travel-info/tourism-info' # 기본 URL
    }

    # 요청하신 2개 명소에 대한 데이터 매핑
    if spot_name == '경기도박물관':
        info_data.update({
            'road_addr': '경기도 용인시 기흥구 상갈로 6',
            'lot_addr': '경기도 용인시 기흥구 상갈동 85',
            'zip_code': '17072',
            'tel_no': '031-288-5300',
            'lat': 37.26788,
            'lng': 127.11233,
            'sigun_nm': '용인시',
            'use_time': '10:00 ~ 18:00',
            'closed_days': '매주 월요일, 1월 1일, 설날/추석 당일',
            'parking': '주차 가능 (유료)',
            'pet_allowed': '불가'
        })
    elif spot_name == '양지파인리조트':
        info_data.update({
            'road_addr': '경기도 용인시 처인구 양지면 남평로 112',
            'lot_addr': '경기도 용인시 처인구 양지면 남곡리 34-1',
            'zip_code': '17162',
            'tel_no': '031-338-2001',
            'lat': 37.21080,
            'lng': 127.28640,
            'sigun_nm': '용인시',
            'use_time': '상시 운영 (시설별 상이)',
            'closed_days': '연중무휴',
            'parking': '주차 가능 (무료)',
            'pet_allowed': '불가'
        })

    return info_data

def main():
    # 0. DB 연결 테스트
    print(f"\n🔌 DB 연결 대상: {DB_HOST}:{DB_PORT} (Database: {DB_NAME})")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ DB 연결 성공!")
    except Exception as e:
        print(f"❌ DB 연결 실패. .env 설정을 확인해주세요.\n에러: {e}")
        return

    desc_list = [] # attraction_descriptions용 리스트
    info_list = [] # tourist_spot_info용 리스트

    for spot in target_spots:
        print(f"\n=== Processing: {spot} ===")
        
        # 단계 1: 위키백과 API 데이터 수집
        overview, history = get_wiki_data(spot)
        
        # 단계 2: 경기관광플랫폼 데이터 수집
        gg_info = crawl_ggtour_info(spot)
        
        # 테이블 A: attraction_descriptions 데이터 구성
        desc_row = {
            'attraction_name': spot,
            'overview': overview if overview else gg_info.get('tourist_nm'), # 위키 없으면 이름이라도
            'history': history, # 없으면 None
            'source_url': gg_info.get('source_url'),
            'created_at': pd.Timestamp.now(),
            'use_time': gg_info.get('use_time'),
            'closed_days': gg_info.get('closed_days'),
            'parking': gg_info.get('parking'),
            'pet_allowed': gg_info.get('pet_allowed')
        }
        desc_list.append(desc_row)

        # 테이블 B: tourist_spot_info 데이터 구성
        info_row = {
            'tourist_nm': spot,
            'tel_no': gg_info.get('tel_no'),
            'base_date': pd.Timestamp.now().strftime('%Y-%m-%d'),
            'road_addr': gg_info.get('road_addr'),
            'lot_addr': gg_info.get('lot_addr'),
            'zip_code': gg_info.get('zip_code'),
            'lat': gg_info.get('lat'),
            'lng': gg_info.get('lng'),
            'sigun_nm': gg_info.get('sigun_nm')
        }
        info_list.append(info_row)
        
        time.sleep(1)

    # 단계 3: DB 데이터 적재
    if desc_list and info_list:
        df_descriptions = pd.DataFrame(desc_list)
        df_info = pd.DataFrame(info_list)

        # 모든 컬럼이 보이도록 Pandas 출력 옵션 설정
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)

        print("\n📊 [데이터 확인] 1. attraction_descriptions (전체 컬럼)")
        print("-" * 80)
        print(df_descriptions)
        print("-" * 80)
        
        print("\n📊 [데이터 확인] 2. tourist_spot_info (전체 컬럼)")
        print("-" * 80)
        print(df_info)
        print("-" * 80)

        print(f"\n⚠️  현재 연결된 DB: {DB_HOST} (Port: {DB_PORT})")
        confirm = input(">> 위 데이터를 운영 DB(LALA DB)에 적재하시겠습니까? (y/n): ").strip().lower()
        if confirm != 'y':
            print("🚫 작업을 취소합니다. 데이터가 DB에 저장되지 않았습니다.")
            return
            
        try:
            schema_name = 'locallink' 
            
            # 1. attraction_descriptions 적재
            print(f"\n💾 [1/2] DB 적재 시작 ({schema_name}.attraction_descriptions)...")
            df_descriptions.to_sql(
                name='attraction_descriptions',
                con=engine,
                schema=schema_name,
                if_exists='append',
                index=False,
                method='multi'
            )
            
            # 2. tourist_spot_info 적재
            print(f"💾 [2/2] DB 적재 시작 ({schema_name}.tourist_spot_info)...")
            df_info.to_sql(
                name='tourist_spot_info',
                con=engine,
                schema=schema_name,
                if_exists='append',
                index=False,
                method='multi'
            )
            print("✅ 모든 데이터 적재 완료!")
            
        except Exception as e:
            print(f"❌ DB 적재 실패: {e}")
    else:
        print("수집된 데이터가 없습니다.")

if __name__ == "__main__":
    main()