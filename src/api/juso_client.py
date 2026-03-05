"""주소기반산업지원서비스 영문주소 API 클라이언트.

엔드포인트: https://business.juso.go.kr/addrlink/addrEngApi.do
인증: Key Vault 'juso-api-key' (confmKey)

사용:
    from src.api.juso_client import translate_address
    en = translate_address("경기도 용인시 기흥구 상갈로 6")
    # → "6, Sanggal-ro, Giheung-gu, Yongin-si, Gyeonggi-do"
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
import json

logger = logging.getLogger(__name__)
logging.getLogger("azure").setLevel(logging.WARNING)

_API_URL = "https://business.juso.go.kr/addrlink/addrEngApi.do"
_API_KEY_CACHE: str | None = None

# 주소에서 괄호/상세주소 제거 패턴
# 예) "경기도 수원시 영통구 봉영로 1613, 지1층 (영통동, 남광하우스토리)"
#   → "경기도 수원시 영통구 봉영로 1613"
_DETAIL_STRIP = re.compile(r",?\s*(지하?\s*\d*층[^\(]*)?\s*\(.*?\)\s*$")
_COMMA_STRIP  = re.compile(r",\s*$")

# "[*미고시]", "[폐업]" 등 대괄호 주석 제거
_ANNOTATION_STRIP = re.compile(r"\s*\[.*?\]\s*$")

# 쉼표 뒤 건물상세(층·호·빌딩명) 모두 제거
# 예) "아주로 37, 아록빌딩 1층" → "아주로 37"
# 예) "덕영대로 924, 지하1층"   → "덕영대로 924"
_POST_COMMA_STRIP = re.compile(r",.*$")

# 도로명+건물번호까지 추출, 이후 건물명/방향어는 extra로 분리
# 예) "경기도 용인시 수지구 신봉로 7 서봉사지" → ("경기도 용인시 수지구 신봉로 7", "서봉사지")
_ROAD_NUM_RE = re.compile(r'^(.+?(?:로|길|대로|번길)\s*\d+(?:-\d+)?)(\s+\S.*)?$')

# 도로명 없을 때 동/리/읍/면 단위까지 추출, 이후는 건물명 extra
# 예) "경기도 용인시 수지구 신봉동 서봉사지" → ("경기도 용인시 수지구 신봉동", "서봉사지")
_DONG_RE = re.compile(r'^(.+?[가-힣]+(?:동|리|읍|면|가)\b)(\s+[가-힣].*)?$')

# 방향·위치 표기어 → 영문 매핑
_DIRECTION_MAP: dict = {
    '앞': 'front',
    '뒤': 'rear',
    '옆': 'side',
    '입구': 'entrance',
    '출구': 'exit',
    '근처': 'near',
    '주변': 'around',
    '내': 'inside',
    '건너편': 'across',
    '사거리': 'intersection',
    '교차로': 'intersection',
    '코앞': 'near',
}


def _get_api_key() -> str:
    global _API_KEY_CACHE
    if _API_KEY_CACHE:
        return _API_KEY_CACHE
    from config.vault_manager import get_vault_manager
    key = get_vault_manager().get_secret("juso-api-key")
    if not key:
        raise RuntimeError("Key Vault에 'juso-api-key' 시크릿이 없습니다.")
    _API_KEY_CACHE = key
    return key


def _romanize_extra(text: str) -> str | None:
    """건물명·방향 표기어를 로마자로 변환.

    hangul_romanize 설치 시 완전 로마자 변환, 미설치 시 방향어 매핑만 수행.
    """
    text = text.strip()
    if not text:
        return None

    # 방향·위치 표기어 단독 → 영문 직접 매핑
    if text in _DIRECTION_MAP:
        return _DIRECTION_MAP[text]

    # hangul_romanize 사용 가능하면 로마자 변환
    try:
        from hangul_romanize import Transliter          # type: ignore
        from hangul_romanize.rule import academic       # type: ignore
        transliter = Transliter(academic)
        romanized = transliter.translit(text)
        # 변환 결과 안에 방향어가 있으면 영문으로 교체
        for kor, eng in _DIRECTION_MAP.items():
            kor_r = transliter.translit(kor)
            romanized = romanized.replace(kor_r, eng)
        return romanized.strip() or None
    except ImportError:
        pass

    # 폴백: 방향어가 끝에 붙은 경우만 처리, 나머지는 한글 원문 반환
    for kor, eng in _DIRECTION_MAP.items():
        if text.endswith(kor):
            prefix = text[: -len(kor)].strip()
            return (f"{prefix} {eng}" if prefix else eng).strip()

    return text  # 마지막 폴백 — 한글 그대로


def _romanize_full_fallback(addr: str) -> str | None:
    """hangul_romanize로 주소 전체를 로마자 변환 (juso API 결과 없을 때 폴백).

    Examples:
        "경기도 평택시 해군기지"    → "Gyeonggi-do Pyeongtaek-si Haegunkiji"
        "경기도 평택남부문예회관 앞" → "Gyeonggi-do Pyeongtaek Nambu Munyegwan front"
    """
    addr = addr.strip()
    if not addr:
        return None
    try:
        from hangul_romanize import Transliter          # type: ignore
        from hangul_romanize.rule import academic       # type: ignore
        transliter = Transliter(academic)
        romanized = transliter.translit(addr)
        # 방향·위치 표기어 영문으로 교체
        for kor, eng in _DIRECTION_MAP.items():
            kor_r = transliter.translit(kor)
            romanized = romanized.replace(kor_r, eng)
        return romanized.strip().title() or None
    except ImportError:
        logger.debug("hangul_romanize 미설치 — 폴백 불가: %s", addr)
        return None


def _split_road_and_extra(addr: str) -> tuple:
    """주소를 (API 검색용 도로·행정 주소, 부가정보) 쌍으로 분리.

    1순위: 도로명+건물번호 패턴  (로/길/대로/번길 + 숫자)
    2순위: 동/리/읍/면 단위 패턴 (도로명 없는 주소)
    3순위: 원문 그대로 사용

    Examples:
        "경기도 용인시 수지구 신봉로 7 서봉사지"  → ("경기도 용인시 수지구 신봉로 7",   "서봉사지")
        "경기도 용인시 수지구 신봉동 서봉사지"    → ("경기도 용인시 수지구 신봉동",     "서봉사지")
        "경기도 평택남부문예회관 앞"              → ("경기도 평택남부문예회관 앞",       "")
    """
    addr = addr.strip()
    addr = _ANNOTATION_STRIP.sub("", addr)   # [*미고시] 등 제거
    addr = _DETAIL_STRIP.sub("", addr)
    addr = _COMMA_STRIP.sub("", addr).strip()

    # 1순위: 도로명+건물번호
    m = _ROAD_NUM_RE.match(addr)
    if m:
        road_part = m.group(1).strip()
        extra     = (m.group(2) or "").strip()
        return road_part, extra

    # 1-b순위: 쉼표 뒤 건물상세(층·호·빌딩명) 제거 후 재시도
    # 예) "아주로 37, 아록빌딩 1층" → "아주로 37"
    addr_trimmed = _POST_COMMA_STRIP.sub("", addr).strip()
    if addr_trimmed != addr:
        m = _ROAD_NUM_RE.match(addr_trimmed)
        if m:
            return m.group(1).strip(), (m.group(2) or "").strip()

    # 2순위: 동/리/읍/면 단위
    m = _DONG_RE.match(addr)
    if m:
        road_part = m.group(1).strip()
        extra     = (m.group(2) or "").strip()
        return road_part, extra

    return addr_trimmed or addr, ""


def translate_address(kor_addr: str | None) -> str | None:
    """한글 도로명주소 → 영문 도로명주소.

    결과 없거나 오류 시 None 반환.
    """
    if not kor_addr or kor_addr.strip() in ("", "NaN"):
        return None

    keyword, extra = _split_road_and_extra(kor_addr)
    if len(keyword) < 4:
        return None

    try:
        api_key = _get_api_key()
        params = urllib.parse.urlencode({
            "confmKey":    api_key,
            "currentPage": 1,
            "countPerPage": 1,
            "keyword":     keyword,
            "resultType":  "json",
        })
        url = f"{_API_URL}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        common = data.get("results", {}).get("common", {})
        err_code = common.get("errorCode", "0")
        if err_code != "0":
            logger.debug("juso API 오류 [%s] %s | 검색어: %s",
                         err_code, common.get("errorMessage"), keyword)
            return None

        jusos = data.get("results", {}).get("juso", [])
        if not jusos:
            # juso DB에 없는 주소(군사시설·랜드마크 등) → 로마자 폴백
            full_addr = keyword + (" " + extra if extra else "")
            fallback = _romanize_full_fallback(full_addr)
            if fallback:
                logger.debug("juso 결과 없음 → 로마자 폴백: %s → %s", full_addr, fallback)
            return fallback

        road_addr_en = jusos[0].get("roadAddr", "").strip()
        if not road_addr_en:
            return None
        # 부가정보(건물명·방향어)가 있으면 로마자로 변환 후 합산
        if extra:
            extra_en = _romanize_extra(extra)
            if extra_en:
                return f"{road_addr_en} ({extra_en})"
        return road_addr_en

    except Exception as exc:
        logger.debug("translate_address 예외: %s | 입력: %s", exc, keyword)
        return None


def reset_key_cache() -> None:
    """테스트용 캐시 초기화."""
    global _API_KEY_CACHE
    _API_KEY_CACHE = None
