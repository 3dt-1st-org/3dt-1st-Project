"""hybrid_place_matching.sql 실제 데이터 end-to-end 테스트.

시나리오:
  1. 쾌적 날씨  → 실내·실외 모두 후보 (현재 DB 날씨 사용)
  2. 악천후 시뮬레이션 → 실내 또는 판단불가(NULL)만 후보
  3. 반경 확장 테스트 → 5km vs 20km 결과 비교

Usage:
    python scripts/ingest/_test_hybrid_matching.py
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import psycopg2

DSN = (
    "host=lala-db.postgres.database.azure.com port=5432 "
    "dbname=postgres user=admin_user password=Aremarem2 sslmode=require"
)

# 테스트 파라미터 ─ 수원화성 좌표 (리뷰 보유 관광지 밀집 지역)
# 날씨 DB 도시는 '화성'이 가장 근접 (DB에 '수원' 없음)
TEST_CITY   = "화성"
USER_LNG    = 127.0152   # 수원화성
USER_LAT    = 37.2808
TOP_K       = 10

# 더미 임베딩 (zero vector 1536차원) ─ 벡터 정렬 비교용
ZERO_VEC = "[" + ",".join(["0.0"] * 1536) + "]"


def get_real_embedding(text: str) -> str | None:
    """Azure OpenAI text-embedding으로 실제 임베딩 생성."""
    try:
        sys.path.insert(0, str(_ROOT))
        from config.vault_manager import get_vault_manager
        vm = get_vault_manager()
        from openai import AzureOpenAI
        import re as _re
        # azure-openai-key는 docent-openai 리소스 (text-embedding-3-small 배포)
        # azure-openai-embedding-endpoint는 별개 리소스 → 이 키로 인증 불가
        # 진단 결과: azure-openai-key + azure-openai-endpoint 조합이 정상 동작
        raw_endpoint = vm.get_secret("azure-openai-endpoint") or \
                       vm.get_secret("azure-openai-embedding-endpoint") or ""
        base_endpoint = _re.sub(r"/openai/.*$", "", raw_endpoint.rstrip("/"))
        client = AzureOpenAI(
            api_key=vm.get_secret("azure-openai-key"),
            azure_endpoint=base_endpoint,
            api_version=vm.get_secret("azure-openai-embedding-api-version") or "2024-02-01",
        )
        deployment = vm.get_secret("azure-openai-embedding-deployment-name") or \
                     vm.get_secret("azure-openai-embedding-deployment")
        resp = client.embeddings.create(model=deployment, input=text)
        vec = resp.data[0].embedding
        return "[" + ",".join(map(str, vec)) + "]"
    except Exception as e:
        print(f"  (임베딩 생성 실패, zero vector 사용: {e})")
        return ZERO_VEC


def make_sql(radius_m: int, override_weather: dict | None = None, query_vec: str | None = None) -> tuple[str, dict]:
    """파라미터 치환된 SQL 반환."""
    sql = (Path(_ROOT) / "sql/analytics/hybrid_place_matching.sql").read_text(encoding="utf-8")
    sql = sql[sql.index("WITH"):]   # ALTER/UPDATE 제거

    params = {
        "city":         TEST_CITY,
        "user_lng":     USER_LNG,
        "user_lat":     USER_LAT,
        "radius_m":     radius_m,
        "query_vector": query_vec or ZERO_VEC,
        "top_k":        TOP_K,
    }

    # 악천후 시뮬레이션: CurrentWeather CTE를 하드코딩 값으로 교체
    if override_weather:
        fake_cte = f"""CurrentWeather AS (
    SELECT
        '{override_weather["outdoor_status"]}'::varchar  AS outdoor_status,
        {override_weather["temperature"]}               AS temperature,
        {override_weather["pm10"]}                      AS pm10,
        {override_weather["pm25"]}                      AS pm25,
        {override_weather["precipitation_type"]}        AS precipitation_type
),"""
        # 기존 CurrentWeather CTE 교체
        import re
        sql = re.sub(
            r"CurrentWeather AS \(.*?(?=\n--\s*2\.)",
            fake_cte + "\n",
            sql,
            flags=re.DOTALL,
        )
        params.pop("city")  # 파라미터 제거 (CTE에 city 없음)

    # 파라미터 치환
    sql = sql.replace(":city",         f"'{params.get('city', TEST_CITY)}'")
    sql = sql.replace(":user_lng",     str(params["user_lng"]))
    sql = sql.replace(":user_lat",     str(params["user_lat"]))
    sql = sql.replace(":radius_m",     str(params["radius_m"]))
    sql = sql.replace(":query_vector", f"'{params['query_vector']}'")
    sql = sql.replace(":top_k",        str(params["top_k"]))
    return sql, params


def run_scenario(label: str, radius_m: int, override_weather: dict | None = None, query_vec: str | None = None) -> None:
    if label:
        print(f"\n{'='*60}")
        print(f"  {label}  (반경 {radius_m/1000:.0f}km)")
        print(f"{'='*60}")

    sql, _ = make_sql(radius_m, override_weather, query_vec)

    conn = psycopg2.connect(DSN)
    cur  = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

        if not rows:
            print("  ⚠️  결과 없음 — 반경 내 후보 장소 없음")
            return

        print(f"  반환 {len(rows)}건\n")
        name_w = 28
        for row in rows:
            r = dict(zip(cols, row))
            indoor = {True: "실내", False: "실외", None: "미분류"}.get(r.get("is_indoor"))
            dist   = r.get("distance_m") or "-"
            vscore = f"{r.get('similarity_score'):.4f}" if r.get("similarity_score") is not None else "N/A"
            print(
                f"  [{r['place_type']:10s}] "
                f"{str(r['place_name']):<{name_w}}  "
                f"{indoor:4s}  "
                f"거리:{dist:>7}m  "
                f"벡터:{vscore}  "
                f"({r.get('sigun_nm','')})"
            )
            if r.get("review_snippet"):
                snippet = str(r["review_snippet"])[:60].replace("\n", " ")
                print(f"    리뷰: {snippet}...")

    except Exception as e:
        print(f"  오류: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"\n기준 위치: {TEST_CITY}  ({USER_LAT}, {USER_LNG})")

    # 실제 사용자 검색어로 임베딩 생성
    QUERY_TEXT = "조용하고 역사적인 실내 전시관"
    print(f"검색어: \"{QUERY_TEXT}\"")
    real_vec = get_real_embedding(QUERY_TEXT)

    # ── 시나리오 1: 실제 임베딩 + 현재 날씨 ───────────────────────────
    run_scenario(
        "시나리오 1 │ 실제 임베딩 + 현재 날씨 (DB 실시간) — 10km",
        radius_m=10_000,
        query_vec=real_vec,
    )

    # ── 시나리오 2: 실제 임베딩 + 악천후 시뮬레이션 ──────────────────
    run_scenario(
        "시나리오 2 │ 실제 임베딩 + 악천후 (비·미세먼지 나쁨) — 10km",
        radius_m=10_000,
        override_weather={
            "outdoor_status":     "미세먼지 나쁨",
            "temperature":        18,
            "pm10":               120,
            "pm25":               60,
            "precipitation_type": 1,
        },
        query_vec=real_vec,
    )

    # ── 시나리오 3: zero vector (순수 거리 기반) 비교 ─────────────────
    run_scenario(
        "시나리오 3 │ zero vector — 순수 거리 기반 비교 — 10km",
        radius_m=10_000,
        query_vec=ZERO_VEC,
    )
