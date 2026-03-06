import psycopg2, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DSN = "host=lala-db.postgres.database.azure.com port=5432 dbname=postgres user=admin_user password=Aremarem2 sslmode=require"
conn = psycopg2.connect(DSN)
cur = conn.cursor()

# 1. 날씨 테이블 locations
cur.execute("SELECT location, count(*) FROM locallink.realtime_weather_conditions GROUP BY location ORDER BY 2 DESC LIMIT 15")
print("=== 날씨 DB locations ===")
for r in cur.fetchall():
    print(f"  {r}")

# 2. '화성' 날씨 최신값
cur.execute("""
SELECT outdoor_status, temperature, pm10, pm25, precipitation_type, record_time
FROM locallink.realtime_weather_conditions
WHERE location = '화성'
ORDER BY record_time DESC LIMIT 3
""")
print("\n=== '화성' 날씨 최신 3건 ===")
for r in cur.fetchall():
    print(f"  {r}")

# 3. 수원화성 반경 10km 관광지 수
cur.execute("""
SELECT count(*) FROM locallink.tourist_spot_info
WHERE lat IS NOT NULL AND lng IS NOT NULL
  AND ST_DWithin(
    ST_SetSRID(ST_MakePoint(127.0152, 37.2808), 4326)::geography,
    ST_SetSRID(ST_MakePoint(lng::float, lat::float), 4326)::geography,
    10000
  )
""")
print("\n=== 반경 10km 관광지 수 ===", cur.fetchone()[0])

# 4. attraction_reviews 분포
cur.execute("SELECT attraction_name, count(*) FROM locallink.attraction_reviews GROUP BY 1")
print("\n=== attraction_reviews 분포 ===")
for r in cur.fetchall():
    print(f"  {r}")

# 5. embedding NULL 여부
cur.execute("SELECT count(*) FROM locallink.attraction_reviews WHERE embedding IS NOT NULL")
print("\n=== 임베딩 보유 리뷰 수 ===", cur.fetchone()[0])

conn.close()

# 6. Key Vault 시크릿
from config.vault_manager import get_vault_manager
vm = get_vault_manager()
keys_to_check = [
    "azure-openai-key", "azure-openai-api-key",
    "azure-openai-embedding-endpoint", "azure-openai-endpoint",
    "azure-openai-embedding-api-version",
    "azure-openai-embedding-deployment-name", "azure-openai-embedding-deployment",
]
print("\n=== Key Vault 시크릿 확인 ===")
for k in keys_to_check:
    try:
        v = vm.get_secret(k)
        display = str(v)[:80] if v else "[빈값]"
        print(f"  [{k}]: {'OK' if v else 'EMPTY'} => {display}")
    except Exception as e:
        print(f"  [{k}]: 오류 => {e}")
