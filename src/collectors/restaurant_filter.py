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
# 1. 위치 기반 음식점 필터링 로직 (반경 150m)
# ==============================================================================
def get_current_location(lat=None, lon=None):
    """사용자의 현재 위치를 반환합니다. (파라미터 없으면 기본값 사용)"""
    if lat is None or lon is None:
        lat = 37.2826
        lon = 127.0145
    return lat, lon

def filter_restaurants_by_location(radius_m=150, lat=None, lon=None):
    """
    사용자가 설정한 GPS 좌표 기준 지정된 반경 내의 음식점 리스트를 추출합니다.
    (gg_restaurant_info 테이블의 실제 컬럼명 반영)
    """
    user_lat, user_lon = get_current_location(lat, lon)
    
    # [수정 포인트] 테이블명: gg_restaurant_info, 컬럼명: refine_wgs84_lat, refine_wgs84_logt
    query = f"""
    SELECT *,
           (6371000 * acos(cos(radians({user_lat})) * cos(radians(refine_wgs84_lat)) 
           * cos(radians(refine_wgs84_logt) - radians({user_lon})) 
           + sin(radians({user_lat})) * sin(radians(refine_wgs84_lat)))) AS distance
    FROM locallink.gg_restaurant_info
    WHERE (6371000 * acos(cos(radians({user_lat})) * cos(radians(refine_wgs84_lat)) 
           * cos(radians(refine_wgs84_logt) - radians({user_lon})) 
           + sin(radians({user_lat})) * sin(radians(refine_wgs84_lat)))) <= {radius_m}
    ORDER BY distance ASC;
    """
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
                
                # 비즈니스 로직: 추출 개수가 10개 미만인 경우 예외 상태 부여
                status = "SKIP_WEIGHTING" if len(results) < 10 else "PROCEED_TO_WEIGHTING"
                return results, status
                
    except Exception as e:
        return [], f"ERROR: {str(e)}"

# ==============================================================================
# 2. 로직 검증 및 실행 테스트
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 [Step 1] Restaurant Location Filtering Test")
    print("=" * 60)

    restaurants, process_status = filter_restaurants_by_location(radius_m=150)

    print(f"📍 Test Location: Suwon Hwaseong Area ({37.2826}, {127.0145})")
    print(f"📊 Total Found: {len(restaurants)} items")
    print(f"🏁 Next Process Status: {process_status}\n")

    if restaurants:
        print("--- Filtered Result List ---")
        for i, res in enumerate(restaurants, 1):
            # 상호명(bizplc_nm)은 0번째 인덱스, 계산된 거리는 마지막 인덱스
            print(f"{i}. {res[0]} (Distance: {res[-1]:.2f}m)")
    else:
        print("⚠️ No data found within the 150m radius.")

    print("=" * 60)