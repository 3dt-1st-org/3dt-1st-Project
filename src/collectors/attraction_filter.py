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
    _vault_url = os.getenv("KEY_VAULT_URL")
    if not _vault_url:
        raise ValueError("❌ .env에 KEY_VAULT_URL이 설정되지 않았습니다.")

    _credential = DefaultAzureCredential()
    _kv_client = SecretClient(vault_url=_vault_url, credential=_credential)    
    
    def _get_secret(name: str) -> str:
        """Key Vault에서 시크릿 값을 가져오는 헬퍼 함수"""
        return _kv_client.get_secret(name).value
    
    return psycopg2.connect(
        host=_get_secret("lala-db-host"),
            port=int(_get_secret("lala-db-port")),
            database=_get_secret("lala-db-name"),
            user=_get_secret("lala-db-user"),
            password=_get_secret("lala-db-password"),
            sslmode="require"
    )

# ==============================================================================
# 1. 위치 기반 명소 필터링 로직
# ==============================================================================
def get_current_location(lat=None, lon=None):
    """
    사용자의 현재 위치를 반환합니다.
    파라미터가 없으면 기본값(테스트용)을 사용합니다.
    
    Args:
        lat: 위도 (기본값: 수원 화성 37.2807)
        lon: 경도 (기본값: 수원 화성 127.0151)
    """
    if lat is None or lon is None:
        # 테스트용 기본 좌표: 수원화성
        lat = 37.2807
        lon = 127.0151
    return lat, lon

def filter_attractions_by_location(radius_m=100, lat=None, lon=None):
    """
    현재 위치 기준 지정된 반경 내의 명소 리스트를 추출합니다.
    
    Args:
        radius_m: 검색 반경 (미터)
        lat: 위도 (None이면 기본 테스트 좌표 사용)
        lon: 경도 (None이면 기본 테스트 좌표 사용)
    """
    user_lat, user_lng = get_current_location(lat, lon)
    
    # 하버사인 공식을 이용한 거리 계산 쿼리
    # 컬럼명: latitude, longitude (제공된 CSV 헤더 기준)
    query = f"""
    SELECT tourist_nm, lot_addr, tel_no, lat, lng,
           (6371000 * acos(cos(radians({user_lat})) * cos(radians(lat)) 
           * cos(radians(lng) - radians({user_lng})) 
           + sin(radians({user_lat})) * sin(radians(lat)))) AS distance
    FROM locallink.tourist_spot_info
    WHERE (6371000 * acos(cos(radians({user_lat})) * cos(radians(lat)) 
           * cos(radians(lng) - radians({user_lng})) 
           + sin(radians({user_lat})) * sin(radians(lat)))) <= {radius_m}
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
            # 0: 이름, 1: 주소, 2: 전화번호, 3: 위도, 4: 경도, 5: 계산된 거리
            print(f"{i}. [{attr[0]}] {attr[1]}")
            print(f"   ∟ Distance: {attr[5]:.2f}m | Tel: {attr[2]}")
    else:
        print("⚠️ No attraction found within the radius. Keep moving!")

    print("=" * 60)