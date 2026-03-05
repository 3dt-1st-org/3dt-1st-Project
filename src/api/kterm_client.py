"""K-Term (국립국어원 온용어) API 클라이언트.

엔드포인트: https://kli.korean.go.kr/term/api/search.do
파라미터 : key, apiSearchWord, num, sort
응답 필드: channel.return_object[].resultlist[].translation  (대역어 = 영문명)

일일 요청 제한 주의 — ReturnCode 022 가 반환되면 즉시 중단.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Optional

import requests

# ── Azure SDK 로그 억제 ─────────────────────────────────────────────────────
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ── 프로젝트 루트 sys.path 등록 ────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.vault_manager import vault as _vault  # noqa: E402

logger = logging.getLogger(__name__)

_ENDPOINT = "https://kli.korean.go.kr/term/api/search.do"

# ── 지리/시설 속성 접미사 → 영어 (긴 접미사부터 매칭) ─────────────────────────
_GEO_SUFFIXES: list[tuple[str, str]] = [
    ("국립공원",  "National Park"),
    ("도립공원",  "Provincial Park"),
    ("시립공원",  "City Park"),
    ("자연공원",  "Natural Park"),
    ("해수욕장",  "Beach"),
    ("유원지",    "Recreation Area"),
    ("놀이공원",  "Amusement Park"),
    ("야영장",    "Campground"),
    ("전망대",    "Observatory"),
    ("박물관",    "Museum"),
    ("미술관",    "Art Museum"),
    ("도서관",    "Library"),
    ("경기장",    "Stadium"),
    ("체육관",    "Gymnasium"),
    ("유적지",    "Historic Site"),
    ("문화재",    "Cultural Heritage"),
    ("저수지",    "Reservoir"),
    ("온천",      "Hot Spring"),
    ("동굴",      "Cave"),
    ("계곡",      "Valley"),
    ("광장",      "Plaza"),
    ("폭포",      "Falls"),
    ("호수",      "Lake"),
    ("공원",      "Park"),
    ("산성",      "Fortress"),
    ("궁궐",      "Palace"),
    ("항구",      "Harbor"),
    ("반도",      "Peninsula"),
    ("평야",      "Plain"),
    ("산림",      "Forest"),
    ("시장",      "Market"),
    ("능",        "Royal Tomb"),
    ("산",        "Mountain"),
    ("봉",        "Peak"),
    ("령",        "Pass"),
    ("재",        "Pass"),
    ("강",        "River"),
    ("천",        "Stream"),
    ("호",        "Lake"),
    ("곶",        "Cape"),
    ("갑",        "Cape"),
    ("만",        "Bay"),
    ("포",        "Port"),
    ("사",        "Temple"),
    ("절",        "Temple"),
    ("암",        "Hermitage"),
    ("궁",        "Palace"),
    ("성",        "Fortress"),
    ("역",        "Station"),
    ("도",        "Island"),
    ("섬",        "Island"),
]


def romanize_fallback(text: str) -> str:
    """K-Term 결과 없을 때 국어 로마자 표기 + 지리 속성 영어 변환 폴백.

    예)
        광교산      →  Gwanggyosan Mountain
        한강        →  Hangang River
        수원화성    →  Su-Wonhwaseong Fortress
        만기사      →  Mangisa Temple
        광교호수공원 →  Gwanggyohosugongwon Park
    """
    try:
        from hangul_romanize import Transliter
        from hangul_romanize.rule import academic
        _tr = Transliter(academic)
    except ImportError:
        logger.warning("hangul-romanize 미설치 — 원문 반환: %s", text)
        return text

    name = text.strip()

    # 긴 접미사부터 체크 (첫 번째 매칭 사용)
    matched_en = ""
    for ko_suffix, en_suffix in _GEO_SUFFIXES:
        if name.endswith(ko_suffix) and len(name) > len(ko_suffix):
            matched_en = en_suffix
            break

    romanized = _tr.translit(name).title()
    result = f"{romanized} {matched_en}".strip() if matched_en else romanized
    logger.debug("[%s] → fallback 로마자: %s", text, result)
    return result

_API_KEY_CACHE: Optional[str] = None
_DAILY_LIMIT_EXCEEDED = False


def _get_api_key() -> str:
    global _API_KEY_CACHE
    if _API_KEY_CACHE:
        return _API_KEY_CACHE
    key = _vault.get_secret("k-term-api-key")
    if not key:
        raise RuntimeError("k-term-api-key 가 Key Vault에 없습니다.")
    _API_KEY_CACHE = key
    return _API_KEY_CACHE


def _parse_channel(data: dict) -> Optional[str]:
    """API 응답 JSON에서 첫 번째 영문 대역어를 추출."""
    channel = data.get("channel", {})
    top_rc = channel.get("returnCode") or channel.get("return_code")
    raw_ro = channel.get("return_object")

    if isinstance(raw_ro, list):
        ro = raw_ro[0] if raw_ro else {}
    elif isinstance(raw_ro, dict):
        ro = raw_ro
    else:
        ro = {}

    return_code = ro.get("returnCode") if isinstance(ro, dict) else None
    if return_code is None:
        return_code = top_rc

    global _DAILY_LIMIT_EXCEEDED
    rc_str = str(return_code) if return_code is not None else ""
    if rc_str in ("22", "022"):
        logger.error("일일 요청 한도(022) 초과 — 이후 호출 중단.")
        _DAILY_LIMIT_EXCEEDED = True
        return None

    if rc_str not in ("1", ""):
        logger.debug("returnCode=%s — 결과 없음", rc_str)
        return None

    result_list = ro.get("resultlist", []) if isinstance(ro, dict) else []
    if not result_list:
        return None

    for item in result_list:
        if not isinstance(item, dict):
            continue
        translation: str = (item.get("translation") or "").strip()
        translation_cc: str = (item.get("translation_cc") or "").lower().strip()

        if not translation:
            continue
        if any("\uAC00" <= c <= "\uD7A3" for c in translation):
            continue
        if translation_cc and translation_cc not in ("영어", "en", "英語", "영어(영국)", "영어(미국)"):
            logger.debug("translation_cc=%s — 비영어 건너뜀", translation_cc)
            continue
        return translation

    return None


def translate(
    text: str,
    *,
    api_key: Optional[str] = None,
    sleep_sec: float = 0.5,
    max_retries: int = 3,
) -> Optional[str]:
    """한국어 텍스트를 온용어 API로 검색해 첫 번째 영문 대역어를 반환."""
    global _DAILY_LIMIT_EXCEEDED

    if _DAILY_LIMIT_EXCEEDED:
        logger.warning("일일 요청 한도 초과 — 이후 호출 모두 건너뜁니다.")
        return None

    if not text or not text.strip():
        return None

    if api_key is None:
        api_key = _get_api_key()

    params = {
        "key": api_key,
        "apiSearchWord": text.strip(),
        "num": "10",
        "start": "1",
        "sort": "wt",
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(_ENDPOINT, params=params, timeout=10)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            logger.warning("[%s] 타임아웃 (시도 %d/%d)", text, attempt, max_retries)
            time.sleep(sleep_sec * attempt)
            continue
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response else 0
            if 500 <= status < 600:
                logger.warning("[%s] 서버 오류 %d (시도 %d/%d)", text, status, attempt, max_retries)
                time.sleep(sleep_sec * attempt)
                continue
            logger.error("[%s] HTTP 오류 %d — 건너뜀", text, status)
            return None
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] 요청 실패: %s", text, exc)
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.error("[%s] JSON 파싱 실패 — 응답: %.300s", text, resp.text)
            return None

        logger.debug("[%s] 원본 응답: %s", text, data)

        result = _parse_channel(data)
        time.sleep(sleep_sec)

        if _DAILY_LIMIT_EXCEEDED:
            return None

        if result is None:
            result = romanize_fallback(text)
            logger.debug("[%s] K-Term 결과 없음 → 폴백: %s", text, result)

        return result

    logger.warning("[%s] 최대 재시도 초과 — 건너뜀", text)
    return None


# ── 음식점 업태 → 영어 (긴 키부터 매칭) ──────────────────────────────────────
_BIZ_TYPE_MAP: list[tuple[str, str]] = [
    ("패스트푸드",   "Fast Food"),
    ("해산물",     "Seafood Restaurant"),
    ("삼겹살",     "BBQ Restaurant"),
    ("갈비",      "Korean BBQ"),
    ("뷔페",      "Buffet"),
    ("커피숍",     "Cafe"),
    ("베이커리",    "Bakery"),
    ("휴게음식점",   "Snack Bar"),
    ("일반음식점",   "Restaurant"),
    ("제과점",     "Bakery"),
    ("한식",      "Korean Restaurant"),
    ("일식",      "Japanese Restaurant"),
    ("중식",      "Chinese Restaurant"),
    ("양식",      "Western Restaurant"),
    ("분식",      "Korean Snack Bar"),
    ("카페",      "Cafe"),
    ("까페",      "Cafe"),
    ("커피",      "Cafe"),
    ("경양식",    "Western Restaurant"),
    ("치킨",      "Fried Chicken"),
    ("피자",      "Pizza"),
    ("횟집",      "Seafood Restaurant"),
    ("고기",      "BBQ Restaurant"),
    ("족발",      "Korean Pork Restaurant"),
    ("냉면",      "Noodle Restaurant"),
    ("국밥",      "Korean Soup Restaurant"),
    ("곱창",      "Korean Offal Restaurant"),
    ("해장국",     "Hangover Soup Restaurant"),
    ("주점",      "Bar"),
    ("호프",      "Bar"),
    ("제과",      "Bakery"),
]


def _map_biz_type(biz_type: str | None) -> str:
    """업태 한국어 → 영어 레이블. 매칭 없으면 'Restaurant'."""
    if not biz_type:
        return "Restaurant"
    for ko, en in _BIZ_TYPE_MAP:
        if ko in biz_type:
            return en
    return "Restaurant"


def romanize_restaurant_fallback(text: str, biz_type: str | None = None) -> str:
    """K-Term 결과 없을 때 음식점명 → 로마자 + (업종) 형식 폴백.

    예)
        할머니네 집, 한식   →  Halmeoninejip (Korean Restaurant)
        스타벅스,  카페     →  Seutabeogseu (Cafe)
        홍길동치킨, 치킨    →  Honggildongchikin (Fried Chicken)
    """
    try:
        from hangul_romanize import Transliter
        from hangul_romanize.rule import academic
        _tr = Transliter(academic)
    except ImportError:
        logger.warning("hangul-romanize 미설치 — 원문 반환: %s", text)
        return text

    romanized = _tr.translit(text.strip()).title()
    biz_en = _map_biz_type(biz_type)
    result = f"{romanized} ({biz_en})"
    logger.debug("[%s] → restaurant fallback: %s", text, result)
    return result


def reset_daily_limit_flag() -> None:
    """테스트용: 일일 한도 플래그 초기화."""
    global _DAILY_LIMIT_EXCEEDED
    _DAILY_LIMIT_EXCEEDED = False