"""
Tests for rank_restaurants() in src/services/restaurant_docent.py

Covers:
- Decimal -> float conversion fix (PR #124): card_score_raw / daangn_score_raw
  from PostgreSQL may arrive as decimal.Decimal, causing TypeError in IQR arithmetic.
- Duplicate restaurant name deduplication: same name from multiple cities must not
  appear more than once in the top-10 result.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.restaurant_docent import rank_restaurants


def _make_cursor(rows: list[tuple]) -> MagicMock:
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    return cursor


class TestRankRestaurantsDecimalFix:
    """Decimal values from DB must not cause TypeError in IQR / min-max logic."""

    def test_decimal_scores_do_not_raise(self):
        """card_score_raw as Decimal should be converted to float without error."""
        rows = [
            ("맛집A", Decimal("1500000.00"), Decimal("42")),
            ("맛집B", Decimal("800000.00"),  Decimal("18")),
            ("맛집C", Decimal("2200000.00"), Decimal("75")),
        ]
        cursor = _make_cursor(rows)
        result = rank_restaurants(["맛집A", "맛집B", "맛집C"], cursor)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_decimal_scores_ranking_is_stable(self):
        """Highest combined score restaurant should rank first."""
        rows = [
            ("맛집저점수", Decimal("100.00"),     Decimal("5")),
            ("맛집고점수", Decimal("9999999.00"), Decimal("999")),
            ("맛집중간",   Decimal("500000.00"),  Decimal("50")),
        ]
        cursor = _make_cursor(rows)
        result = rank_restaurants(["맛집저점수", "맛집고점수", "맛집중간"], cursor)
        assert result[0] == "맛집고점수"

    def test_zero_decimal_scores_return_original_order(self):
        """All-zero scores result in equal ranking; function should still return list."""
        rows = [
            ("식당X", Decimal("0"), Decimal("0")),
            ("식당Y", Decimal("0"), Decimal("0")),
        ]
        cursor = _make_cursor(rows)
        result = rank_restaurants(["식당X", "식당Y"], cursor)
        assert set(result) == {"식당X", "식당Y"}

    def test_empty_rows_falls_back_to_input(self):
        """No DB rows -> return original candidate list (up to 10)."""
        cursor = _make_cursor([])
        names = ["식당1", "식당2", "식당3"]
        result = rank_restaurants(names, cursor)
        assert result == names

    def test_mixed_int_float_decimal_scores(self):
        """int and float values should also be handled correctly alongside Decimal."""
        rows = [
            ("IntScore",   1000000,   30),
            ("FloatScore", 750000.5,  22.5),
            ("DecScore",   Decimal("1200000.00"), Decimal("60")),
        ]
        cursor = _make_cursor(rows)
        result = rank_restaurants(["IntScore", "FloatScore", "DecScore"], cursor)
        assert isinstance(result, list)
        assert len(result) > 0


class TestRankRestaurantsDeduplicate:
    """Same restaurant name from multiple cities must appear once in the result."""

    def test_duplicate_names_from_multiple_cities_removed(self):
        """동경 appears in Suwon AND Yongin rows → must appear only once in result."""
        rows = [
            ("동경", Decimal("500000"), Decimal("20")),   # Suwon row
            ("동경", Decimal("300000"), Decimal("10")),   # Yongin row (same name)
            ("우리집", Decimal("800000"), Decimal("50")),
            ("우리집", Decimal("600000"), Decimal("30")),
            ("우리집", Decimal("400000"), Decimal("15")),
            ("벙커", Decimal("1200000"), Decimal("80")),
        ]
        cursor = _make_cursor(rows)
        names = ["동경", "동경", "우리집", "우리집", "우리집", "벙커"]
        result = rank_restaurants(names, cursor)
        assert result.count("동경") == 1
        assert result.count("우리집") == 1
        assert result.count("벙커") == 1

    def test_no_duplicates_in_result_at_all(self):
        """Regardless of how many duplicate DB rows exist, result has unique names."""
        rows = [
            ("A식당", Decimal("100"), Decimal("10")),
            ("A식당", Decimal("200"), Decimal("20")),
            ("B식당", Decimal("300"), Decimal("30")),
            ("B식당", Decimal("400"), Decimal("40")),
            ("C식당", Decimal("500"), Decimal("50")),
        ]
        cursor = _make_cursor(rows)
        result = rank_restaurants(["A식당", "A식당", "B식당", "B식당", "C식당"], cursor)
        assert len(result) == len(set(result)), "Result contains duplicate names"

    def test_top10_limit_after_dedup(self):
        """After deduplication, result is still capped at 10."""
        # 15 unique restaurants, each with 2 city rows = 30 raw rows
        names = [f"식당{i}" for i in range(15)]
        rows = []
        for i, name in enumerate(names):
            rows.append((name, Decimal(str(i * 100000)), Decimal(str(i * 10))))
            rows.append((name, Decimal(str(i * 50000)),  Decimal(str(i * 5))))
        cursor = _make_cursor(rows)
        result = rank_restaurants(names * 2, cursor)
        assert len(result) <= 10
        assert len(result) == len(set(result))
