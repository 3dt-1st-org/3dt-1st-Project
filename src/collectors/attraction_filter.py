import os
import psycopg2
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

# ==============================================================================
# 0. 인프라 설정 (Key Vault & DB Connection)
# ==============================================================================
load_dotenv()

def get_db_connection():
    """Key Vault에서 인증 정보를 로드하여 DB 연결 객체를 생성합니다."""
    vault_url = os.getenv("KEY_VAULT_URL")
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=vault_url, credential=credential)
    
    # 보안 시크릿 로드
    db_password = kv_client.get_secret("db-password").value
    
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        database=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "admin_user"),
        password=db_password
    )

# ==============================================================================
# 1. 위치 기반 명소 필터링 로직
# ==============================================================================
def get_current_location():
    """
    사용자의 현재 위치를 반환합니다. 
    (테스트용: 수원 화성 인근 좌표 37.2807, 127.0151)
    """
    # 데이터 상의 수원화성 좌표: 37.2807973662, 127.0151841956
    lat = 37.2807
    lon = 127.0151
    return lat, lon

def filter_attractions_by_location(radius_m=30):
    """
    현재 위치 기준 지정된 반경 내의 명소 리스트를 추출합니다.
    명소 테이블명: gg_attraction_info (가칭, 실제 테이블명에 맞춰 수정 필요)
    """
    user_lat, user_lon = get_current_location()
    
    # 하버사인 공식을 이용한 거리 계산 쿼리
    # 컬럼명: latitude, longitude (제공된 CSV 헤더 기준)
    query = f"""
    SELECT attraction_name, road_address, entrance_fee, latitude, longitude,
           (6371000 * acos(cos(radians({user_lat})) * cos(radians(latitude)) 
           * cos(radians(longitude) - radians({user_lon})) 
           + sin(radians({user_lat})) * sin(radians(latitude)))) AS distance
    FROM locallink.filtered_attractions
    WHERE (6371000 * acos(cos(radians({user_lat})) * cos(radians(latitude)) 
           * cos(radians(longitude) - radians({user_lon})) 
           + sin(radians({user_lat})) * sin(radians(latitude)))) <= {radius_m}
    ORDER BY distance ASC;
    """
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
                
                # 비즈니스 로직: 명소는 하나라도 발견되면 도슨트 기능을 제공할 수 있음
                status = "ATTRACTION_DETECTED" if len(results) > 0 else "NO_ATTRACTION_NEARBY"
                return results, status
                
    except Exception as e:
        return [], f"ERROR: {str(e)}"

# ==============================================================================
# 2. 로직 검증 및 실행 테스트
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 [Step 1] Attraction Location Filtering Test")
    print("=" * 60)

    # 명소는 정교한 진입 판정을 위해 반경 100m로 테스트
    attractions, process_status = filter_attractions_by_location(radius_m=100)

    user_lat, user_lon = get_current_location()
    print(f"📍 Current GPS: ({user_lat}, {user_lon})")
    print(f"📊 Total Found: {len(attractions)} items")
    print(f"🏁 Status: {process_status}\n")

    if attractions:
        print("--- Detected Attraction List ---")
        for i, attr in enumerate(attractions, 1):
            # 0: 이름, 1: 주소, 5: 계산된 거리
            print(f"{i}. [{attr[0]}] {attr[1]}")
            print(f"   ∟ Distance: {attr[5]:.2f}m | Fee: {attr[2]}")
    else:
        print("⚠️ No attraction found within the radius. Keep moving!")

    print("=" * 60)