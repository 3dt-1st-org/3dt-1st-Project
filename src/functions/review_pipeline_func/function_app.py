"""
review_pipeline_func — 매일 새벽 2시(KST) 타이머 트리거
=======================================================
수행 작업:
  1) 지역별 관광지 리뷰 배치 수집 (load_review_pipeline.run_batch_for_area)
  2) 식당 리뷰 수집              (load_restaurant_review.run_restaurant_pipeline)

환경 변수 (App Settings / local.settings.json)
  KEY_VAULT_URL               — Azure Key Vault URL (필수)
  REVIEW_PIPELINE_SCHEDULE    — CRON (기본: "0 0 17 * * *" = 02:00 KST)
  REVIEW_PIPELINE_AREAS       — JSON 배열, 각 원소 {lat, lng, radius_m, label}
  REVIEW_PIPELINE_RESTAURANTS — JSON 배열, 식당명 문자열 목록

주의: 전체 파이프라인(LLM + 임베딩 + DB)이 오래 걸릴 수 있으므로
     Flex Consumption / Premium Plan 권장 (host.json functionTimeout 참고).
"""

import json
import logging
import os
import sys

import azure.functions as func

# ─────────────────────────────────────────────────────────────────────────────
# 프로젝트 루트를 sys.path에 추가
#   review_pipeline_func/ → functions/ → src/ → project_root/
# ─────────────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.collectors.load_review_pipeline import run_batch_for_area      # noqa: E402
from src.collectors.load_restaurant_review import run_restaurant_pipeline # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# 상수 / 환경 변수
# ─────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("review-pipeline-func")

# 기본 수집 지역 (환경변수 REVIEW_PIPELINE_AREAS로 덮어쓰기 가능)
_DEFAULT_AREAS: list[dict] = [
    {"lat": 37.2808, "lng": 127.0152, "radius_m": 10_000, "label": "수원화성"},
    {"lat": 37.2410, "lng": 127.1775, "radius_m": 10_000, "label": "용인"},
    {"lat": 37.4200, "lng": 127.1265, "radius_m": 10_000, "label": "성남"},
]

# 기본 식당 목록 (환경변수 REVIEW_PIPELINE_RESTAURANTS로 덮어쓰기 가능)
_DEFAULT_RESTAURANTS: list[str] = [
    "무무옥", "로우파이브신풍", "사과당 수원행궁점", "달달한부엌",
    "위해브투데이", "키프(KIFF)", "사케도로보", "킵댓 행궁점",
    "누크녹카라멜하우스", "다담",
]

REVIEW_SCHEDULE: str = os.getenv("REVIEW_PIPELINE_SCHEDULE", "0 0 17 * * *")

REVIEW_AREAS: list[dict] = json.loads(
    os.getenv("REVIEW_PIPELINE_AREAS", json.dumps(_DEFAULT_AREAS))
)

RESTAURANT_LIST: list[str] = json.loads(
    os.getenv("REVIEW_PIPELINE_RESTAURANTS", json.dumps(_DEFAULT_RESTAURANTS))
)

# ─────────────────────────────────────────────────────────────────────────────
# Azure Function App
# ─────────────────────────────────────────────────────────────────────────────
app = func.FunctionApp()


@app.timer_trigger(
    schedule=REVIEW_SCHEDULE,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def review_pipeline_daily(timer: func.TimerRequest) -> None:
    """매일 새벽 2시(KST) — 명소 및 식당 리뷰 파이프라인 실행."""

    if timer.past_due:
        logger.warning("⚠️  타이머 지연 감지: 이전에 놓친 실행이 지금 실행됩니다.")

    logger.info("=" * 64)
    logger.info("🚀 리뷰 파이프라인 시작")
    logger.info("=" * 64)

    # ── 1) 명소 리뷰 배치 수집 ────────────────────────────────────────────
    logger.info(f"[명소] 수집 대상 지역: {len(REVIEW_AREAS)}개")
    attraction_errors: list[str] = []

    for area in REVIEW_AREAS:
        label = area.get("label", f"({area['lat']}, {area['lng']})")
        radius_m = area.get("radius_m", 10_000)
        logger.info(f"  → {label}  반경 {radius_m // 1000}km 처리 중...")
        try:
            run_batch_for_area(area["lat"], area["lng"], radius_m)
            logger.info(f"  ✅ {label} 완료")
        except Exception as exc:
            msg = f"{label}: {exc}"
            logger.exception(f"  ❌ {msg}")
            attraction_errors.append(msg)

    # ── 2) 식당 리뷰 수집 ─────────────────────────────────────────────────
    logger.info(f"[식당] 수집 대상: {len(RESTAURANT_LIST)}개")
    restaurant_errors: list[str] = []

    for restaurant in RESTAURANT_LIST:
        logger.info(f"  → '{restaurant}' 처리 중...")
        try:
            run_restaurant_pipeline(restaurant)
            logger.info(f"  ✅ '{restaurant}' 완료")
        except Exception as exc:
            msg = f"{restaurant}: {exc}"
            logger.exception(f"  ❌ {msg}")
            restaurant_errors.append(msg)

    # ── 결과 요약 ─────────────────────────────────────────────────────────
    total_errors = len(attraction_errors) + len(restaurant_errors)
    logger.info("=" * 64)
    if total_errors == 0:
        logger.info("🎉 리뷰 파이프라인 완료 — 에러 없음")
    else:
        logger.warning(
            f"⚠️  리뷰 파이프라인 완료 — 에러 {total_errors}건\n"
            + "\n".join(f"  · {e}" for e in attraction_errors + restaurant_errors)
        )
    logger.info("=" * 64)
