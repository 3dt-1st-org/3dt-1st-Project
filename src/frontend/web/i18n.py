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
        # 신규 키
        "map_ai_placeholder":      "AI가 이 장소를 추천하는 이유를 분석 중…",
        "settings_fontsize":       "글자 크기",
        "settings_loc_consent":    "위치 기반 데이터 동의",
        "settings_loc_consent_desc": "위치 정보를 기반으로 주변 명소 및 음식점을 탐색합니다.",
        # 프라이버시 카드
        "settings_privacy":        "개인정보 체념문",
        "settings_privacy_body":   "라라는 주변 명소 탐색을 위해 위치 정보를 사용합니다. 수집된 데이터는 서비스 제공 목적 외 사용되지 않으며 제3자에게 제공되지 않습니다.",
        "settings_privacy_detail": "자세히 보기",
        "settings_privacy_full":   "▶ 수집하는 정보: 위치 정보(위도/경도)\n▶ 이용 목적: 주변 명소 및 음식점 정보 제공\n▶ 보유 기간: 로컬스토리지에만 저장되며 서버로 전송되지 않습니다.\n▶ 파으:동의 시 위치 기반 탐색 기능이 동작하지 않는 구역이 발생할 수 있습니다.",
        "settings_close":          "닫기",
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
        "map_ai_placeholder":      "Analyzing why AI recommends this place…",
        "settings_fontsize":       "Font Size",
        "settings_loc_consent":    "Location Data Consent",
        "settings_loc_consent_desc": "Used to explore nearby attractions and restaurants.",
        "settings_privacy":        "Privacy Policy",
        "settings_privacy_body":   "LALA uses location data to show nearby attractions. Data is not shared with third parties.",
        "settings_privacy_detail": "View Details",
        "settings_privacy_full":   "▶ Data collected: Location (lat/lng)\n▶ Purpose: Nearby places discovery\n▶ Retention: Stored in localStorage only\n▶ Opt-out: Turn off the consent toggle above.",
        "settings_close":          "Close",
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
        "map_ai_placeholder":      "AIがこの場所を推薦する理由を分析中…",
        "settings_fontsize":       "文字サイズ",
        "settings_loc_consent":    "位置情報データの同意",
        "settings_loc_consent_desc": "周辺の観光地・飲食店を探索するために使用します。",
        "settings_privacy":        "プライバシーポリシー",
        "settings_privacy_body":   "LALAは周辺の観光地探索のために位置情報を使用します。データは第三者に提供されません。",
        "settings_privacy_detail": "詳細を見る",
        "settings_privacy_full":   "▶ 収集情報: 位置(緯度/経度)\n▶ 利用目的: 周辺スポットの提供\n▶ 保持期間: localStorageのみ\n▶ オプトアウト: 同意トグルをオフにすると位置機能は停止します。",
        "settings_close":          "閉じる",
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
