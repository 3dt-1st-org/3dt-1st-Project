"""
tourist_spot_info 에 is_indoor BOOLEAN 컬럼을 추가하고,
GPT-4o-mini 로 관광지명을 기반으로 실내/실외를 일괄 분류하여 저장.

Usage:
    python scripts/ingest/classify_tourist_indoor.py [--dry-run]
"""
from __future__ import annotations
import sys, json, time, argparse
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import psycopg2
from config.vault_manager import get_vault_manager

DSN = (
    "host=lala-db.postgres.database.azure.com port=5432 "
    "dbname=postgres user=admin_user password=Aremarem2 sslmode=require"
)

# ── GPT 분류 프롬프트 ──────────────────────────────────────────────────────
SYSTEM_PROMPT = """당신은 한국 관광지 분류 전문가입니다.
관광지 이름만 보고 실내(indoor) 또는 실외(outdoor) 장소인지 분류하세요.

규칙:
- 박물관, 미술관, 전시관, 갤러리, 아쿠아리움, 수족관, 공연장, 영화관, 실내 체험관, 
  문화원, 도서관, 쇼핑몰, 마켓(실내), 센터, 케이블카 승강장, 온천(실내), 찜질방 → "indoor"
- 성곽, 궁궐(야외), 공원, 해변, 산, 폭포, 계곡, 항구, 광장, 거리, 다리, 전망대(야외), 
  유적지, 사찰(야외 경내), 저수지, 섬, 숲, 동굴(야외 접근) → "outdoor"
- 복합 시설, 판단 불가 → "unknown"

응답 형식 (JSON 배열, 다른 텍스트 없이):
[
  {"name": "관광지명", "is_indoor": true | false | null, "reason": "한 줄 이유"},
  ...
]
"""

BATCH_SIZE = 30  # GPT 1회 호출당 처리 건수


def get_openai_client(vm):
    from openai import AzureOpenAI
    import re as _re
    raw_ep = (vm.get_secret("azure-openai-endpoint") or "").rstrip("/")
    client = AzureOpenAI(
        api_key=vm.get_secret("azure-openai-key"),
        azure_endpoint=raw_ep,
        api_version=vm.get_secret("azure-openai-version") or "2024-02-01",
    )
    deployment = vm.get_secret("azure-openai-deployment-name") or "gpt-4o-mini"
    return client, deployment


def classify_batch(client, deployment: str, names: list[str]) -> list[dict]:
    """names 리스트를 GPT에 전달해 분류 결과 반환."""
    user_msg = json.dumps(names, ensure_ascii=False)
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"다음 관광지 목록을 분류하세요:\n{user_msg}"},
        ],
        temperature=0,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content.strip()
    # JSON 파싱: {"results": [...]} 또는 [...] 형태 모두 처리
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        return parsed
    # json_object 모드는 최상위가 dict여야 함 → 배열이 들어있는 키 찾기
    for v in parsed.values():
        if isinstance(v, list):
            return v
    raise ValueError(f"예상치 못한 GPT 응답 구조: {raw[:200]}")


def main(dry_run: bool = False):
    vm = get_vault_manager()
    client, deployment = get_openai_client(vm)
    print(f"[GPT] 배포: {deployment}")

    conn = psycopg2.connect(DSN)
    cur  = conn.cursor()

    # 1. is_indoor 컬럼 추가 (없으면)
    cur.execute("""
        ALTER TABLE locallink.tourist_spot_info
        ADD COLUMN IF NOT EXISTS is_indoor BOOLEAN DEFAULT NULL;
    """)
    conn.commit()
    print("[DB] is_indoor 컬럼 준비 완료")

    # 2. 분류 대상 목록 조회 (is_indoor IS NULL 인 행만)
    cur.execute("""
        SELECT tourist_nm
        FROM   locallink.tourist_spot_info
        WHERE  is_indoor IS NULL
        ORDER  BY tourist_nm
    """)
    all_names = [r[0] for r in cur.fetchall()]
    print(f"[DB] 분류 대상: {len(all_names)}건")

    if not all_names:
        print("모두 분류 완료됨.")
        conn.close()
        return

    # 3. 배치 분류
    results: dict[str, bool | None] = {}
    total_batches = (len(all_names) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(all_names), BATCH_SIZE):
        batch = all_names[i: i + BATCH_SIZE]
        batch_no = i // BATCH_SIZE + 1
        print(f"  배치 {batch_no}/{total_batches} ({len(batch)}건) ...", end=" ", flush=True)

        try:
            classified = classify_batch(client, deployment, batch)
            for item in classified:
                name    = item.get("name", "")
                indoor  = item.get("is_indoor")  # True / False / None
                reason  = item.get("reason", "")
                results[name] = indoor
                status = "실내" if indoor is True else ("실외" if indoor is False else "불명")
                print(f"\n    {name:30s} → {status:4s}  ({reason})", end="")
            print()
        except Exception as e:
            print(f"\n    오류: {e} — 해당 배치 건너뜀")

        # Rate limit 방지
        if batch_no < total_batches:
            time.sleep(0.5)

    print(f"\n[분류 완료] 총 {len(results)}건")
    indoor_cnt  = sum(1 for v in results.values() if v is True)
    outdoor_cnt = sum(1 for v in results.values() if v is False)
    null_cnt    = sum(1 for v in results.values() if v is None)
    print(f"  실내: {indoor_cnt}  실외: {outdoor_cnt}  불명: {null_cnt}")

    if dry_run:
        print("[DRY-RUN] DB 업데이트 생략")
        conn.close()
        return

    # 4. DB 업데이트
    updated = 0
    for name, indoor in results.items():
        cur.execute(
            "UPDATE locallink.tourist_spot_info SET is_indoor = %s WHERE tourist_nm = %s",
            (indoor, name),
        )
        updated += cur.rowcount

    conn.commit()
    print(f"[DB] {updated}건 업데이트 완료")

    # 5. 결과 확인
    cur.execute("""
        SELECT is_indoor, count(*)
        FROM locallink.tourist_spot_info
        GROUP BY 1 ORDER BY 1 NULLS LAST
    """)
    print("\n[DB 최종 분포]")
    for row in cur.fetchall():
        label = "실내" if row[0] is True else ("실외" if row[0] is False else "불명(NULL)")
        print(f"  {label}: {row[1]}건")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="DB 업데이트 없이 분류 결과만 출력")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
