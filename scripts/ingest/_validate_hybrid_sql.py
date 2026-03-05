"""hybrid_place_matching.sql 문법 검증 스크립트 (일회성)."""
import psycopg2

sql = open("sql/analytics/hybrid_place_matching.sql", encoding="utf-8").read()

vec = "[" + ",".join(["0.01"] * 1536) + "]"
test_sql = (
    sql
    .replace(":city",         "'수원'")
    .replace(":user_lng",     "126.9990")
    .replace(":user_lat",     "37.2665")
    .replace(":radius_m",     "5000")
    .replace(":query_vector", f"'{vec}'")
    .replace(":top_k",        "3")
)

# WITH 절부터 잘라냄 (ALTER/UPDATE 제외)
main_sql = test_sql[test_sql.index("WITH"):]

conn = psycopg2.connect(
    "host=lala-db.postgres.database.azure.com port=5432 "
    "dbname=postgres user=admin_user password=Aremarem2 sslmode=require"
)
cur = conn.cursor()
try:
    cur.execute("EXPLAIN " + main_sql)
    rows = cur.fetchall()
    print(f"EXPLAIN 성공 — 플랜 라인 수: {len(rows)}")
    for r in rows[:8]:
        print(" ", r[0])
except Exception as e:
    print("오류:", e)
finally:
    conn.close()
