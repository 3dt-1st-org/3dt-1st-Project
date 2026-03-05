#!/usr/bin/env python
"""locallink.gyeonggi_events.title 영문명 보강 (Azure OpenAI 번역).

Azure OpenAI Chat Completion API를 사용해 행사 제목을 자연스러운 영어로 번역.
  - 30건씩 배치 요청 → 996건 약 34회 API 호출
  - [기관명], (날짜), <부제> 등 구조적 요소 보존
  - Key Vault에서 엔드포인트/키/배포명 자동 조회

Usage:
    python scripts/ingest/enrich_event_names_en.py \\
        --dsn "host=... dbname=... user=... password=... sslmode=require" \\
        [--batch-size 30] \\
        [--commit-size 500] \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.vault_manager import get_vault_manager  # noqa: E402

try:
    import psycopg
    def db_connect(dsn: str):
        return psycopg.connect(dsn)
except ModuleNotFoundError:
    import psycopg2 as psycopg
    def db_connect(dsn: str):
        return psycopg.connect(dsn)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Azure SDK 로그 억제
import logging as _logging
_logging.getLogger("azure").setLevel(_logging.WARNING)
_logging.getLogger("openai").setLevel(_logging.WARNING)
_logging.getLogger("httpx").setLevel(_logging.WARNING)

TABLE   = "locallink.gyeonggi_events"
SRC_COL = "title"
TGT_COL = "title_en"

_SYSTEM_PROMPT = """\
You are a professional Korean-to-English translator specializing in cultural event titles.

Rules:
1. Translate each Korean event title into concise, natural English.
2. Preserve structural markers exactly as-is: [text], (text), <text>, 《text》, '전시', numbers, dates like (8/30) or (~7/10).
3. For institution names inside [brackets], translate or romanize them (e.g. [경기도박물관] → [Gyeonggi Museum], [삼성화재모빌리티뮤지엄] → [Samsung Fire Mobility Museum]).
4. Translate common event types: 전시→Exhibition, 축제→Festival, 공모전→Contest, 학술대회→Conference, 학술회의→Academic Conference, 워크숍→Workshop, 콘서트→Concert, 운영안내→Operation Notice, 휴관→Closed Notice, 모집→Recruitment, 업무협약→MOU Signing, 개소식→Opening Ceremony, 협약식→Agreement Ceremony.
5. Foreign loanwords written in Korean: 락→Rock, 페스티벌→Festival, 뮤지엄→Museum, 콘서트→Concert, 헤리티지→Heritage, 리빙랩→Living Lab, 홈커밍→Homecoming.
6. Return ONLY a JSON array of translated strings, same order and count as input. No explanations.

Example input: ["[경기도박물관] 설 연휴 운영안내", "2025 아티즌 락페스티벌 (8/30)"]
Example output: ["[Gyeonggi Museum] Lunar New Year Holiday Notice", "2025 Artizen Rock Festival (8/30)"]
"""

# ── Azure OpenAI 클라이언트 ────────────────────────────────────────────────────
_aoai_client = None
_aoai_deployment = None

def _get_aoai_client():
    global _aoai_client, _aoai_deployment
    if _aoai_client is not None:
        return _aoai_client, _aoai_deployment

    try:
        from openai import AzureOpenAI
    except ImportError:
        raise ImportError("openai 패키지 미설치 → pip install openai")

    v = get_vault_manager()
    endpoint   = v.get_secret("azure-openai-endpoint")
    api_key    = v.get_secret("azure-openai-key")
    api_ver    = v.get_secret("azure-openai-version") or "2024-02-01"
    deployment = v.get_secret("azure-openai-deployment-name")

    if not all([endpoint, api_key, deployment]):
        raise RuntimeError("Key Vault에서 Azure OpenAI 시크릿을 찾을 수 없습니다.")

    _aoai_client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_ver,
    )
    _aoai_deployment = deployment
    logger.info("Azure OpenAI 연결 완료 (deployment: %s)", deployment)
    return _aoai_client, _aoai_deployment


def translate_batch(titles: list[str]) -> list[str]:
    """titles 리스트를 Azure OpenAI로 일괄 번역. 실패 시 원문 반환."""
    client, deployment = _get_aoai_client()

    user_msg = json.dumps(titles, ensure_ascii=False)
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        raw = resp.choices[0].message.content.strip()
        # JSON 배열 추출 (```json ... ``` 래핑 제거)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        if isinstance(result, list) and len(result) == len(titles):
            return result
        logger.warning("응답 건수 불일치 (%d → %d) — 원문 유지", len(titles), len(result))
        return titles
    except Exception as e:
        logger.warning("번역 실패 (%s) — 원문 유지", e)
        return titles


def ensure_column(cursor) -> None:
    cursor.execute(
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {TGT_COL} TEXT;"
    )
    logger.info("컬럼 확인 완료: %s.%s", TABLE, TGT_COL)


def fetch_all_pending(cursor) -> list[str]:
    """미처리 고유 title 전체 로드."""
    cursor.execute(
        f"""
        SELECT DISTINCT {SRC_COL}
        FROM   {TABLE}
        WHERE  {SRC_COL} IS NOT NULL
          AND  ({TGT_COL} IS NULL OR {TGT_COL} = '')
        ORDER  BY {SRC_COL};
        """
    )
    return [row[0] for row in cursor.fetchall()]


def run(dsn: str, batch_size: int, commit_size: int, dry_run: bool) -> None:
    conn = db_connect(dsn)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            ensure_column(cur)
            conn.commit()
            logger.info("미처리 행사명 로드 중...")
            titles = fetch_all_pending(cur)

        if not titles:
            logger.info("보강할 행사 없음 — 종료.")
            return

        total = len(titles)
        n_batches = (total + batch_size - 1) // batch_size
        logger.info("총 %d 건 Azure OpenAI 번역 시작 (%d건 배치 × %d회)...",
                    total, batch_size, n_batches)

        t0 = time.time()

        # dry-run: 첫 배치(최대 20건)만 번역하고 출력
        if dry_run:
            preview = titles[:min(batch_size, 20)]
            translated = translate_batch(preview)
            for orig, en in zip(preview, translated):
                logger.info("[DRY-RUN] %-50s  ->  %s", orig, en)
            if total > 20:
                logger.info("... 외 %d 건 (--dry-run: 처음 20건만 표시)", total - 20)
            return

        # 1단계: OpenAI 배치 번역
        converted = []   # (title_en, title)
        for b_idx in range(n_batches):
            chunk = titles[b_idx * batch_size: (b_idx + 1) * batch_size]
            translated = translate_batch(chunk)
            for orig, en in zip(chunk, translated):
                converted.append((en, orig))
            logger.info("번역 진행: %d / %d (%.0f%%)",
                        min((b_idx + 1) * batch_size, total),
                        total,
                        min((b_idx + 1) * batch_size, total) / total * 100)
            time.sleep(0.3)   # rate limit 여유

        elapsed_trans = time.time() - t0
        logger.info("번역 완료: %d 건 (%.1f초)", total, elapsed_trans)

        # 2단계: 배치 UPDATE (title 기준, id 없음)
        SQL = (
            f"UPDATE {TABLE} "
            f"SET {TGT_COL} = %s "
            f"WHERE {SRC_COL} = %s "
            f"AND ({TGT_COL} IS NULL OR {TGT_COL} = '');"
        )

        total_updated = 0
        for chunk_start in range(0, total, commit_size):
            chunk = converted[chunk_start: chunk_start + commit_size]
            with conn.cursor() as cur:
                cur.executemany(SQL, chunk)
                total_updated += cur.rowcount
            conn.commit()

        elapsed_total = time.time() - t0
        logger.info(
            "완료 — 갱신: %d행 / 소요: %.1f초",
            total_updated, elapsed_total,
        )

    except Exception:
        conn.rollback()
        logger.exception("오류 발생 — 롤백 완료.")
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="행사명 한국어 → 영문명 보강 (Azure OpenAI 번역)"
    )
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument(
        "--batch-size", type=int, default=30,
        help="OpenAI 1회 요청당 번역 건수 (기본 30)",
    )
    parser.add_argument(
        "--commit-size", type=int, default=500,
        help="DB 커밋 단위 (기본 500)",
    )
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 처음 20건만 출력")
    args = parser.parse_args()

    run(args.dsn, args.batch_size, args.commit_size, args.dry_run)


if __name__ == "__main__":
    main()


