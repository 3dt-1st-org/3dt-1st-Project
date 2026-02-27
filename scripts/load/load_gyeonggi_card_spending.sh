#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   PGPASSWORD='1111' \
#   PSQL_CONN='host=localhost port=5433 dbname=postgres user=admin_user' \
#   CSV_DIR='/Users/rudin/Documents/MicrosoftDataSchool/1st-project/3dt-1st-Project/data/raw/경기도_카드소비_데이터_2025' \
#   ./load_gyeonggi_card_spending.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CSV_DIR="${CSV_DIR:-${PROJECT_ROOT}/data/raw/경기도_카드소비_데이터_2025}"
PSQL_CONN="${PSQL_CONN:-host=localhost port=5433 dbname=postgres user=admin_user}"
CSV_ENCODING="${CSV_ENCODING:-UTF8}"
TARGET_TABLE="${TARGET_TABLE:-locallink.gyeonggi_card_spending_stats}"
DDL_FILE="${DDL_FILE:-${PROJECT_ROOT}/sql/ddl/gyeonggi_card_spending_status.sql}"

if [[ -z "${PGPASSWORD:-}" ]]; then
  echo "ERROR: PGPASSWORD is not set."
  exit 1
fi

if [[ ! -d "$CSV_DIR" ]]; then
  echo "ERROR: CSV_DIR does not exist: $CSV_DIR"
  exit 1
fi

if [[ ! -f "$DDL_FILE" ]]; then
  echo "ERROR: DDL file does not exist: $DDL_FILE"
  exit 1
fi

shopt -s nullglob
files=("$CSV_DIR"/*.csv)
shopt -u nullglob

if [[ ${#files[@]} -eq 0 ]]; then
  echo "ERROR: No CSV files found in: $CSV_DIR"
  exit 1
fi

# One-time setup
psql "$PSQL_CONN" -v ON_ERROR_STOP=1 <<SQL
CREATE SCHEMA IF NOT EXISTS locallink;
SQL

psql "$PSQL_CONN" -v ON_ERROR_STOP=1 -f "$DDL_FILE"

psql "$PSQL_CONN" -v ON_ERROR_STOP=1 -c "TRUNCATE TABLE ${TARGET_TABLE};"

for f in "${files[@]}"; do
  base="$(basename "$f" .csv)"
  city="${base##*_}"
  city_escaped="${city//\'/\'\'}"

  echo "loading: $f (city=$city)"

  psql "$PSQL_CONN" -v ON_ERROR_STOP=1 <<SQL
CREATE TEMP TABLE gyeonggi_card_spending_stats_stg_tmp (
  ta_ymd CHAR(8),
  cty_rgn_no VARCHAR(20),
  admi_cty_no VARCHAR(20),
  card_tpbuz_cd VARCHAR(20),
  card_tpbuz_nm_1 VARCHAR(100),
  card_tpbuz_nm_2 VARCHAR(100),
  hour SMALLINT,
  sex VARCHAR(10),
  age SMALLINT,
  day SMALLINT,
  amt NUMERIC,
  cnt BIGINT
);
\copy gyeonggi_card_spending_stats_stg_tmp (ta_ymd, cty_rgn_no, admi_cty_no, card_tpbuz_cd, card_tpbuz_nm_1, card_tpbuz_nm_2, hour, sex, age, day, amt, cnt) FROM '$f' WITH (FORMAT csv, HEADER true, ENCODING '$CSV_ENCODING')
INSERT INTO ${TARGET_TABLE} (
  ta_ymd, city, card_tpbuz_nm_1, card_tpbuz_nm_2,
  hour, sex, age, day, amt, cnt
)
SELECT
  to_date(ta_ymd::text, 'YYYYMMDD'), '${city_escaped}', card_tpbuz_nm_1, card_tpbuz_nm_2,
  hour, sex, age, day, amt, cnt
FROM gyeonggi_card_spending_stats_stg_tmp;
SQL
done

echo "Done. Loaded ${#files[@]} files into $TARGET_TABLE."
