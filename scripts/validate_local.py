"""
로컬 통합 검증 스크립트
=======================
Flask test_client 방식으로 실행 — 별도 서버 기동 불필요

테스트 항목:
  1. /api/ios/v1/health          → db/openai/speech 모두 ok
  2. GET /api/ios/v1/weather     → source 확인 (db > open-meteo 폴백 순)
  3. WEATHER_DB_ENABLED=false    → source=open-meteo 강제
  4. POST /api/ios/v1/docent/script (attraction) → 리뷰 인용 포함 여부
  5. GET /api/ios/v1/places      → 결과 리스트 반환 확인

사용법:
  python scripts/validate_local.py
"""
from __future__ import annotations
import json
import os
import sys
import time

# ─── 프로젝트 루트를 sys.path에 추가 ─────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# ─── KV에서 필수 env 주입 (Flask app 초기화 전에 반드시 먼저) ─────────────────
from dotenv import load_dotenv                                  # noqa: E402
load_dotenv()

from config.vault_manager import vault                          # noqa: E402

def _kv(name: str) -> str:
    v = vault.get_secret(name) or ""
    return v.strip()

# ── App Service에서는 KV Reference로 자동 주입되는 env vars를 로컬에서 직접 설정 ──
IOS_API_KEY = _kv("lala-ios-api-key")
os.environ["IOS_API_KEY"]           = IOS_API_KEY
os.environ.setdefault("WEATHER_DB_ENABLED", "true")

# DB (Flask web app은 DB_DSN 단일 env var 사용)
os.environ["DB_DSN"] = _kv("db-dsn")

# Azure OpenAI (health check + docent service가 env var 직접 읽음)
os.environ["AZURE_OPENAI_ENDPOINT"]        = _kv("azure-openai-endpoint")
os.environ["AZURE_OPENAI_KEY"]             = _kv("azure-openai-key")
os.environ["AZURE_OPENAI_VERSION"]         = _kv("azure-openai-version")
os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"] = _kv("azure-openai-deployment-name")

# Azure Speech
os.environ["AZURE_SPEECH_KEY"]    = _kv("azure-speech-key")
os.environ["AZURE_SPEECH_REGION"] = _kv("azure-speech-region")

print("=" * 60)
print("🔑 API Key 로드:", IOS_API_KEY[:8] + "..." if IOS_API_KEY else "❌ MISSING")
print("🔑 DB_DSN 로드:", "SET" if os.environ.get("DB_DSN") else "❌ MISSING")
print("🔑 OpenAI 로드:", "SET" if os.environ.get("AZURE_OPENAI_KEY") else "❌ MISSING")
print("🔑 Speech 로드:", "SET" if os.environ.get("AZURE_SPEECH_KEY") else "❌ MISSING")
print("=" * 60)

# ─── Flask app 생성 ────────────────────────────────────────────────────────────
from src.frontend.web.app import create_app                     # noqa: E402

app = create_app()
app.config["TESTING"] = True

# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────
PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results: list[tuple[str, bool, str]] = []

def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    icon = PASS if passed else FAIL
    msg = f"{icon} {name}"
    if detail:
        msg += f"  →  {detail}"
    print(msg)


# ─────────────────────────────────────────────────────────────────────────────
# 수원 화성 좌표 (테스트 기준점)
LAT, LNG = 37.2808, 127.0152
HEADERS  = {"X-API-Key": IOS_API_KEY}
# ─────────────────────────────────────────────────────────────────────────────

with app.test_client() as client:

    # ── 1. /health ─────────────────────────────────────────────────────────────
    print("\n[1] Health Check")
    r = client.get("/api/ios/v1/health", headers=HEADERS)
    body = r.get_json() or {}
    ok = r.status_code == 200 and body.get("status") == "ok"
    check("health status=ok", ok, json.dumps(body, ensure_ascii=False))
    check("health db=ok",     body.get("db") == "ok",     f"db={body.get('db')}")
    check("health openai=ok", body.get("openai") == "ok", f"openai={body.get('openai')}")
    check("health speech=ok", body.get("speech") == "ok", f"speech={body.get('speech')}")

    # ── 2. 날씨 DB 조회 ───────────────────────────────────────────────────────
    print("\n[2] Weather — DB-first (WEATHER_DB_ENABLED=true)")
    os.environ["WEATHER_DB_ENABLED"] = "true"
    r = client.get(f"/api/ios/v1/weather?lat={LAT}&lng={LNG}", headers=HEADERS)
    body = r.get_json() or {}
    source = body.get("source", "")
    ok_status = r.status_code == 200
    check("weather HTTP 200", ok_status, f"status={r.status_code}")
    check("weather has temp/temperature", "temp" in body or "temperature" in body,
          f"keys={list(body.keys())}")
    check("weather source=db (DB에 최근 데이터 있으면)",
          source == "db",
          f"source={source!r}  ← DB miss 시 open-meteo 정상")
    if source != "db":
        print(f"   {WARN}  realtime_weather_conditions에 70분 이내 데이터 없음 → open-meteo 폴백 (정상)")
        # DB 미스는 데이터 공백(weather_air_func 타이밍)이므로 fail 항목에서 제외
        results[-1] = (results[-1][0], True, results[-1][2] + "  [soft]")

    # ── 3. 날씨 폴백 (DB 비활성화) ─────────────────────────────────────────────
    print("\n[3] Weather — WEATHER_DB_ENABLED=false 폴백")
    os.environ["WEATHER_DB_ENABLED"] = "false"
    r = client.get(f"/api/ios/v1/weather?lat={LAT}&lng={LNG}", headers=HEADERS)
    body = r.get_json() or {}
    source = body.get("source", "")
    check("weather HTTP 200 (fallback)", r.status_code == 200, f"status={r.status_code}")
    check("weather source != db", source != "db", f"source={source!r}")
    os.environ["WEATHER_DB_ENABLED"] = "true"  # 원복

    # ── 4. 도슨트 (attraction) ────────────────────────────────────────────────
    print("\n[4] Docent Script — attraction")
    # place_id = MD5(attraction_name || '|' || sigun_nm)  — 칠보산 수원시
    payload = {
        "place_id": "36f5042e8e938f4530c05724ae2d6839",
        "category": "attraction",
        "language": "ko",
        "mode": "brief",
    }
    r = client.post(
        "/api/ios/v1/docent/script",
        json=payload,
        headers=HEADERS,
    )
    body = r.get_json() or {}
    script_text = body.get("script", "")
    check("docent HTTP 200", r.status_code == 200, f"status={r.status_code}")
    check("docent script non-empty", len(script_text) > 50,
          f"len={len(script_text)} chars")
    # 리뷰 인용 특징 어구 (pick_story_reviews 흔적)
    story_hints = ["\ubc29\ubb38\uac1d", '"', '\u201c', "\ud6c4\uae30", "\ub290\ub08c", "\ubd84\uc704\uae30", "\uc778\uc0c1"]
    has_story = any(h in script_text for h in story_hints)
    check("docent has review-style phrases (선택)", has_story,
          script_text[:120].replace("\n", " ") + "…")

    # ── 5. 도슨트 (restaurant) ────────────────────────────────────────────────
    print("\n[5] Docent Script — restaurant")
    # place_id = MD5(bizplc_nm || refine_roadnm_addr)  — 별자리다방
    rest_payload = {
        "place_id": "51af65ff41ce8fa15ccbe87d03b89023",
        "category": "restaurant",
        "language": "ko",
        "mode": "brief",
    }
    r = client.post(
        "/api/ios/v1/docent/script",
        json=rest_payload,
        headers=HEADERS,
    )
    body = r.get_json() or {}
    script_text = body.get("script", "")
    check("restaurant docent HTTP 200", r.status_code == 200, f"status={r.status_code}")
    check("restaurant docent non-empty", len(script_text) > 50, f"len={len(script_text)}")

    # ── 6. 장소 목록 ─────────────────────────────────────────────────────────
    print("\n[6] Places list")
    r = client.get(
        f"/api/ios/v1/places?lat={LAT}&lng={LNG}&category=attraction&scope=radius",
        headers=HEADERS,
    )
    body = r.get_json() or {}
    places = body.get("places", body.get("items", []))
    check("places HTTP 200", r.status_code == 200, f"status={r.status_code}")
    check("places list non-empty", len(places) > 0, f"count={len(places)}")

# ─── 요약 ─────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
total  = len(results)
passed = sum(1 for _, p, _ in results if p)
failed = total - passed
print(f"결과: {passed}/{total} 통과  {('— ' + str(failed) + '건 실패') if failed else '— 전부 통과 🎉'}")
print("=" * 60)

if failed:
    print("\n실패 항목:")
    for name, p, detail in results:
        if not p:
            print(f"  {FAIL} {name}: {detail}")
    sys.exit(1)
