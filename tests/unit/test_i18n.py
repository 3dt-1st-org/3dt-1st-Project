"""Unit tests for i18n.py language dictionary completeness."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.frontend.web.i18n import TRANSLATIONS, SUPPORTED, DEFAULT, t


def test_supported_languages_exist():
    for lang in SUPPORTED:
        assert lang in TRANSLATIONS, f"Language '{lang}' missing from TRANSLATIONS"


def test_default_language_is_supported():
    assert DEFAULT in SUPPORTED


def test_all_keys_present_in_both_languages():
    """ko/en 양쪽에 동일한 키가 있어야 한다."""
    ko_keys = set(TRANSLATIONS["ko"].keys())
    en_keys = set(TRANSLATIONS["en"].keys())

    missing_in_en = ko_keys - en_keys
    missing_in_ko = en_keys - ko_keys

    assert not missing_in_en, f"Keys present in ko but missing in en: {missing_in_en}"
    assert not missing_in_ko, f"Keys present in en but missing in ko: {missing_in_ko}"


def test_event_status_keys_exist():
    """행사 카드 진행중/종료됨 레이블 키가 양쪽 언어에 존재해야 한다."""
    for lang in ("ko", "en"):
        assert "map_event_status_ongoing" in TRANSLATIONS[lang]
        assert "map_event_status_ended" in TRANSLATIONS[lang]


def test_event_status_english_values():
    """영문 이벤트 상태 값이 한국어가 아닌 영어로 제공되어야 한다."""
    assert TRANSLATIONS["en"]["map_event_status_ongoing"] == "Ongoing"
    assert TRANSLATIONS["en"]["map_event_status_ended"] == "Ended"


def test_outdoor_status_keys_exist():
    """날씨 outdoor_status 번역 키가 양쪽 언어에 존재해야 한다."""
    keys = [
        "map_outdoor_comfortable",
        "map_outdoor_rain",
        "map_outdoor_pm_bad",
        "map_outdoor_pm_very_bad",
        "map_outdoor_moderate",
    ]
    for lang in ("ko", "en"):
        for key in keys:
            assert key in TRANSLATIONS[lang], f"Missing key '{key}' in lang '{lang}'"


def test_planner_period_keys_exist():
    """하루 일정 시간대 레이블 키가 양쪽 언어에 존재해야 한다."""
    keys = [
        "map_planner_period_morning",
        "map_planner_period_afternoon",
        "map_planner_period_evening",
    ]
    for lang in ("ko", "en"):
        for key in keys:
            assert key in TRANSLATIONS[lang], f"Missing key '{key}' in lang '{lang}'"


def test_planner_period_english_values():
    """영문 시간대 레이블이 올바른 영어 값이어야 한다."""
    assert TRANSLATIONS["en"]["map_planner_period_morning"] == "Morning"
    assert TRANSLATIONS["en"]["map_planner_period_afternoon"] == "Afternoon"
    assert TRANSLATIONS["en"]["map_planner_period_evening"] == "Evening"


def test_no_empty_values():
    """어떤 키도 빈 문자열 값을 가지면 안 된다."""
    for lang, entries in TRANSLATIONS.items():
        for key, value in entries.items():
            assert value.strip(), f"Empty value for key '{key}' in lang '{lang}'"


def test_t_returns_key_when_missing():
    """존재하지 않는 키를 요청하면 키 이름을 그대로 반환해야 한다."""
    result = t("nonexistent_key_xyz")
    assert result == "nonexistent_key_xyz"
