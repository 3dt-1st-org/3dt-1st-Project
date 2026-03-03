"""
i18n.py — 다국어 번역 사전 (KO / EN / JA)
Flask session['lang'] 값을 읽어 t(key) 함수로 번역 반환
"""
from __future__ import annotations

SUPPORTED = ("ko", "en", "ja")
DEFAULT   = "ko"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ko": {
        # GNB
        "nav_map":      "🗺 지도",
        "nav_settings": "설정",
        # 지도 필터
        "filter_all":         "전체",
        "filter_attraction":  "🏛 명소",
        "filter_restaurant":  "🍽 음식점",
        # 지도 UI
        "map_loading":       "주변 장소를 불러오는 중…",
        "map_no_results":    "주변에 장소가 없어요",
        "map_error_title":   "🗺 지도를 불러올 수 없어요",
        "map_error_domain":  "Kakao Maps API 키의 허용 도메인에 아래 주소를 추가해주세요.",
        "map_error_link":    "Kakao Developers 바로가기",
        # 온보딩
        "splash_sub":        "내 주변 경기도 명소 탐색",
        "privacy_title":     "서비스 이용 동의",
        "privacy_btn":       "동의하고 시작하기",
        # 설정 페이지
        "settings_title":       "설정",
        "settings_lang":        "언어 설정",
        "settings_lang_desc":   "앱에서 사용할 언어를 선택해주세요.",
        "settings_location":    "위치 권한 재설정",
        "settings_loc_desc":    "위치 권한이 거부된 경우 아래 안내를 따라주세요.",
        "settings_loc_chrome":  "Chrome: 주소창 왼쪽 🔒 → 위치 → 허용",
        "settings_loc_firefox": "Firefox: 주소창 왼쪽 🔒 → 권한 → 위치 → 허용",
        "settings_loc_safari":  "Safari: 설정 → Safari → 위치 → 허용",
        "settings_loc_reset":   "변경 후 페이지를 새로고침해주세요.",
        "settings_about":       "앱 정보",
        "settings_version":     "버전",
    },
    "en": {
        "nav_map":      "🗺 Map",
        "nav_settings": "Settings",
        "filter_all":         "All",
        "filter_attraction":  "🏛 Attractions",
        "filter_restaurant":  "🍽 Restaurants",
        "map_loading":       "Loading nearby places…",
        "map_no_results":    "No places found nearby",
        "map_error_title":   "🗺 Map unavailable",
        "map_error_domain":  "Please add the following URL to your Kakao Maps API allowed domains.",
        "map_error_link":    "Kakao Developers",
        "splash_sub":        "Explore Gyeonggi attractions near you",
        "privacy_title":     "Terms of Service",
        "privacy_btn":       "Agree & Continue",
        "settings_title":       "Settings",
        "settings_lang":        "Language",
        "settings_lang_desc":   "Select the language to use in the app.",
        "settings_location":    "Reset Location Permission",
        "settings_loc_desc":    "If location access was denied, follow the steps below.",
        "settings_loc_chrome":  "Chrome: Click 🔒 in address bar → Location → Allow",
        "settings_loc_firefox": "Firefox: Click 🔒 in address bar → Permissions → Access Your Location → Allow",
        "settings_loc_safari":  "Safari: Settings → Safari → Location → Allow",
        "settings_loc_reset":   "Refresh the page after changing permissions.",
        "settings_about":       "About",
        "settings_version":     "Version",
    },
    "ja": {
        "nav_map":      "🗺 地図",
        "nav_settings": "設定",
        "filter_all":         "すべて",
        "filter_attraction":  "🏛 観光地",
        "filter_restaurant":  "🍽 レストラン",
        "map_loading":       "周辺のスポットを読み込み中…",
        "map_no_results":    "周辺にスポットが見つかりません",
        "map_error_title":   "🗺 地図を読み込めません",
        "map_error_domain":  "Kakao Maps APIキーの許可ドメインに以下のURLを追加してください。",
        "map_error_link":    "Kakao Developers へ",
        "splash_sub":        "近くの京畿道スポットを探索",
        "privacy_title":     "利用規約",
        "privacy_btn":       "同意して開始",
        "settings_title":       "設定",
        "settings_lang":        "言語設定",
        "settings_lang_desc":   "アプリで使用する言語を選択してください。",
        "settings_location":    "位置情報の許可をリセット",
        "settings_loc_desc":    "位置情報が拒否されている場合は、以下の手順に従ってください。",
        "settings_loc_chrome":  "Chrome: アドレスバーの🔒 → 位置情報 → 許可",
        "settings_loc_firefox": "Firefox: アドレスバーの🔒 → 権限 → 位置情報 → 許可",
        "settings_loc_safari":  "Safari: 設定 → Safari → 位置情報 → 許可",
        "settings_loc_reset":   "変更後、ページを更新してください。",
        "settings_about":       "アプリ情報",
        "settings_version":     "バージョン",
    },
}


def get_lang() -> str:
    """현재 요청의 Flask session에서 언어 코드를 반환. 기본값 'ko'."""
    try:
        from flask import session
        lang = session.get("lang", DEFAULT)
        return lang if lang in SUPPORTED else DEFAULT
    except RuntimeError:
        return DEFAULT


def t(key: str) -> str:
    """번역 키를 현재 언어로 변환. 키가 없으면 키 자체를 반환."""
    lang = get_lang()
    return TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT]).get(key, key)
