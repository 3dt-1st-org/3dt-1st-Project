"""Event-driven weather change simulation.

Behavior:
1) Run `daily_plan_main.py` once at startup (morning plan).
2) Poll latest weather row from DB repeatedly.
3) If a NEW observation arrives and weather state changed, run `weather_main.py` immediately.

This avoids fixed time-slot recommendations and reacts at the moment new data is ingested.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.weather_planner import WeatherTravelPlanner


class WeatherRealtimeSimulator:
    """React immediately when weather state changes on newly ingested records."""

    def __init__(
        self,
        lat: float = 37.2635,
        lng: float = 127.0090,
        poll_seconds: int = 30,
        run_minutes: int = 30,
        city_prefix: str = "수원",
    ):
        self.lat = lat
        self.lng = lng
        self.poll_seconds = poll_seconds
        self.run_minutes = run_minutes
        self.city_prefix = city_prefix

        self.planner = WeatherTravelPlanner(lat, lng)

        self.python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        self.daily_plan_script = PROJECT_ROOT / "src" / "main" / "daily_plan_main.py"
        self.weather_script = PROJECT_ROOT / "src" / "main" / "weather_main.py"

        self.last_seen_record_time = None
        self.last_seen_state = None

    def _latest_weather_row(self) -> dict | None:
        query = """
            SELECT location, record_time, temperature, precipitation_type, pm10, pm25, outdoor_status
            FROM locallink.realtime_weather_conditions
            WHERE location LIKE %s
            ORDER BY record_time DESC
            LIMIT 1
        """
        with psycopg2.connect(self.planner.dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (f"{self.city_prefix}%",))
                row = cur.fetchone()
                return dict(row) if row else None

    @staticmethod
    def _build_state(row: dict) -> str:
        precip = row.get("precipitation_type") or 0
        status = row.get("outdoor_status") or "정보 없음"
        pm10 = row.get("pm10") or 0
        pm25 = row.get("pm25") or 0
        return f"precip={precip}|status={status}|pm10={pm10}|pm25={pm25}"

    def _run_script(self, script_path: Path, language: str, timeout: int = 90) -> int:
        cmd = [
            str(self.python_exe),
            str(script_path),
            "--language",
            language,
        ]
        print(f"\n[EXEC] {' '.join(cmd)}")

        env = dict(**os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("[STDERR]")
            print(result.stderr)
        return result.returncode

    def run(self):
        print("\n" + "=" * 70)
        print("Real-time weather reaction test")
        print("=" * 70)
        print(f"City prefix: {self.city_prefix}")
        print(f"Poll interval: {self.poll_seconds}s")
        print(f"Run duration: {self.run_minutes} minutes")

        print("\n[STEP 1] Morning plan start -> daily_plan_main.py")
        rc = self._run_script(self.daily_plan_script, language="Korean")
        if rc != 0:
            print(f"[WARN] daily_plan_main.py exited with code {rc}")

        print("\n[STEP 2] Start event-driven watch")
        deadline = time.time() + (self.run_minutes * 60)

        while time.time() < deadline:
            row = self._latest_weather_row()
            if not row:
                print("[INFO] No weather row found. waiting...")
                time.sleep(self.poll_seconds)
                continue

            record_time = row["record_time"]
            state = self._build_state(row)

            if self.last_seen_record_time is None:
                self.last_seen_record_time = record_time
                self.last_seen_state = state
                print(f"[BASELINE] {record_time} | {state}")
                time.sleep(self.poll_seconds)
                continue

            if record_time <= self.last_seen_record_time:
                print("[NO NEW DATA] waiting...")
                time.sleep(self.poll_seconds)
                continue

            print(f"\n[NEW DATA] {record_time}")
            print(f"[STATE] {state}")

            prev_state = self.last_seen_state
            self.last_seen_record_time = record_time
            self.last_seen_state = state

            if state == prev_state:
                print("[NO CHANGE] state unchanged -> skip weather_main.py")
                time.sleep(self.poll_seconds)
                continue

            print("[CHANGE DETECTED] Run weather_main.py immediately")
            rc = self._run_script(self.weather_script, language="English")
            if rc != 0:
                print(f"[WARN] weather_main.py exited with code {rc}")

            time.sleep(self.poll_seconds)

        print("\n" + "=" * 70)
        print("Simulation finished")
        print("=" * 70)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Event-driven weather reaction simulator")
    parser.add_argument("--latitude", type=float, default=37.2635)
    parser.add_argument("--longitude", type=float, default=127.0090)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--run-minutes", type=int, default=30)
    parser.add_argument("--city-prefix", type=str, default="수원")
    return parser.parse_args()


def main():
    args = parse_args()
    simulator = WeatherRealtimeSimulator(
        lat=args.latitude,
        lng=args.longitude,
        poll_seconds=args.poll_seconds,
        run_minutes=args.run_minutes,
        city_prefix=args.city_prefix,
    )
    simulator.run()


if __name__ == "__main__":
    main()
