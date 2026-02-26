#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   PGPASSWORD='yourpassword' \
#   PSQL_CONN='host=localhost port=5432 dbname=yourdb user=youruser' \
#   CSV_DIR='/Users/rudin/Documents/MicrosoftDataSchool/1st-project/data/경기도_카드소비_데이터_2025' \
#   ./load_gyeonggi_card_spending.sh

CSV_DIR="${CSV_DIR:-/Users/rudin/Documents/MicrosoftDataSchool/1st-project/data/경기도_카드소비_데이터_2025}"
PSQL_CONN="${PSQL_CONN:-host=localhost port=5432 dbname=yourdb user=youruser}"
CSV_ENCODING="${CSV_ENCODING:-UTF8}"
TARGET_TABLE="${TARGET_TABLE:-locallink.gyeonggi_card_spending_stats}"
STG_TABLE="${STG_TABLE:-locallink.gyeonggi_card_spending_stats_stg}"

if [[ -z "${PGPASSWORD:-}" ]]; then
  echo "ERROR: PGPASSWORD is not set."
  exit 1
fi

if [[ ! -d "$CSV_DIR" ]]; then
  echo "ERROR: CSV_DIR does not exist: $CSV_DIR"
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
ALTER TABLE ${TARGET_TABLE}
ADD COLUMN IF NOT EXISTS city VARCHAR(50);

CREATE TABLE IF NOT EXISTS ${STG_TABLE} (
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
SQL

for f in "${files[@]}"; do
  base="$(basename "$f" .csv)"
  city="${base##*_}"
  city_escaped="${city//\'/\'\'}"

  echo "loading: $f (city=$city)"

  psql "$PSQL_CONN" -v ON_ERROR_STOP=1 -c "TRUNCATE TABLE ${STG_TABLE};"

  psql "$PSQL_CONN" -v ON_ERROR_STOP=1 -c "\copy ${STG_TABLE} (ta_ymd, cty_rgn_no, admi_cty_no, card_tpbuz_cd, card_tpbuz_nm_1, card_tpbuz_nm_2, hour, sex, age, day, amt, cnt) FROM '$f' WITH (FORMAT csv, HEADER true, ENCODING '$CSV_ENCODING')"

  psql "$PSQL_CONN" -v ON_ERROR_STOP=1 <<SQL
INSERT INTO ${TARGET_TABLE} (
  ta_ymd, city, cty_rgn_no, admi_cty_no, card_tpbuz_cd, card_tpbuz_nm_1, card_tpbuz_nm_2,
  hour, sex, age, day, amt, cnt
)
SELECT
  ta_ymd, '${city_escaped}', cty_rgn_no, admi_cty_no, card_tpbuz_cd, card_tpbuz_nm_1, card_tpbuz_nm_2,
  hour, sex, age, day, amt, cnt
FROM ${STG_TABLE};
SQL
done

echo "Done. Loaded ${#files[@]} files into $TARGET_TABLE."
