import re
import unittest
from pathlib import Path


class TestDaangnSeedSql(unittest.TestCase):
    def test_city_coverage_for_target_scope(self):
        seed_path = (
            Path(__file__).resolve().parents[2]
            / "sql"
            / "dml"
            / "daangn_target_dongs_seed.sql"
        )
        sql = seed_path.read_text(encoding="utf-8")

        matches = re.findall(r"\('([^']+)'\s*,\s*'([^']+)'\s*,", sql)

        city_counts = {}
        for city, _dong in matches:
            city_counts[city] = city_counts.get(city, 0) + 1

        self.assertIn("수원시", city_counts)
        self.assertIn("용인시", city_counts)
        self.assertIn("평택시", city_counts)

        self.assertGreaterEqual(city_counts["수원시"], 20)
        self.assertGreaterEqual(city_counts["용인시"], 20)
        self.assertGreaterEqual(city_counts["평택시"], 10)

    def test_no_null_dong_slug(self):
        seed_path = (
            Path(__file__).resolve().parents[2]
            / "sql"
            / "dml"
            / "daangn_target_dongs_seed.sql"
        )
        sql = seed_path.read_text(encoding="utf-8")
        self.assertNotIn(", NULL, TRUE)", sql)


if __name__ == "__main__":
    unittest.main()
