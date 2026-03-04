import json
import logging
import os
from datetime import datetime, timedelta

import azure.functions as func
import requests
from azure.eventhub import EventData, EventHubProducerClient

# ==============================================================================
# 상수
# ==============================================================================
KMA_API_URL  = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
MISE_API_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
EVENTHUB_NAME = "weather-air-stream"

# 수원·용인 기상청 격자 좌표 및 에어코리아 측정소명
_STATIONS = {
    "suwon":  {"nx": 61, "ny": 121, "air_station": "신풍동"},
    "yongin": {"nx": 62, "ny": 120, "air_station": "수지"},
}

# ==============================================================================
# 시크릿 (App Settings → Key Vault References)
# ==============================================================================
WEATHER_API_KEY   = os.getenv("WEATHER_API_KEY", "")      # KV: weather-api-key
MISE_API_KEY      = os.getenv("MISE_API_KEY", "")          # KV: mise-api-key
EVENT_HUB_CONN_STR = os.getenv("EVENT_HUB_CONN_STR", "")  # KV: eventhub-conn-str

# ==============================================================================
# 기상청 초단기실황 조회
# ==============================================================================
def _fetch_kma(nx: int, ny: int) -> dict | None:
    """기상청 초단기실황 API 호출 → T1H·RN1·PTY·WSD 추출"""
    # 기상청 API는 ~10분 지연 → 1시간 전 기준시 사용
    now = datetime.now() - timedelta(hours=1)
    params = {
        "pageNo":    "1",
        "numOfRows": "1000",
        "dataType":  "JSON",
        "base_date": now.strftime("%Y%m%d"),
        "base_time": now.strftime("%H00"),
        "nx":        nx,
        "ny":        ny,
        "serviceKey": WEATHER_API_KEY,
    }
    try:
        resp = requests.get(KMA_API_URL, params=params, timeout=5)
        resp.raise_for_status()
        header = resp.json()["response"]["header"]
        if header["resultCode"] != "00":
            logging.warning(f"[KMA] API 오류: {header['resultCode']} - {header['resultMsg']}")
            return None

        items = {i["category"]: i["obsrValue"]
                 for i in resp.json()["response"]["body"]["items"]["item"]}
        return {
            "t1h": items.get("T1H"),   # 기온(°C)
            "rn1": items.get("RN1"),   # 1시간 강수량(mm)
            "pty": items.get("PTY"),   # 강수형태 (0=없음 1=비 2=비/눈 3=눈)
            "wsd": items.get("WSD"),   # 풍속(m/s)
        }
    except Exception as e:
        logging.warning(f"[KMA] 호출 실패 nx={nx} ny={ny}: {e}")
        return None


# ==============================================================================
# 에어코리아 대기오염정보 조회
# ==============================================================================
def _fetch_air(station_name: str) -> dict | None:
    """에어코리아 API 호출 → PM10·PM2.5 추출"""
    params = {
        "serviceKey":  MISE_API_KEY,
        "returnType":  "json",
        "pageNo":      "1",
        "numOfRows":   "1",
        "stationName": station_name,
        "dataTerm":    "DAILY",
        "ver":         "1.3",
    }
    try:
        resp = requests.get(MISE_API_URL, params=params, timeout=5)
        resp.raise_for_status()
        items = resp.json().get("response", {}).get("body", {}).get("items", [])
        if not items:
            logging.warning(f"[AIR] 데이터 없음: {station_name}")
            return None

        # dataTime 기준 최신값 선택
        latest = sorted(items, key=lambda d: d["dataTime"], reverse=True)[0]
        return {
            "pm10":      latest.get("pm10Value"),   # 미세먼지(㎍/㎥)
            "pm25":      latest.get("pm25Value"),   # 초미세먼지(㎍/㎥)
            "data_time": latest.get("dataTime"),
        }
    except Exception as e:
        logging.warning(f"[AIR] 호출 실패 station={station_name}: {e}")
        return None


# ==============================================================================
# Event Hubs 전송
# ==============================================================================
def _send_to_eventhub(payload: dict) -> None:
    """payload dict를 JSON으로 직렬화하여 weather-air-stream으로 전송"""
    with EventHubProducerClient.from_connection_string(
        conn_str=EVENT_HUB_CONN_STR,
        eventhub_name=EVENTHUB_NAME,
    ) as producer:
        batch = producer.create_batch()
        batch.add(EventData(json.dumps(payload, ensure_ascii=False)))
        producer.send_batch(batch)
    logging.info(f"[EventHub] 전송 완료: {EVENTHUB_NAME}")


# ==============================================================================
# Azure Functions 타이머 트리거 (3시간 간격)
# ==============================================================================
app = func.FunctionApp()

@app.timer_trigger(
    schedule="0 0 */3 * * *",
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False,
)
def WeatherAirDataCollector(myTimer: func.TimerRequest) -> None:
    if myTimer.past_due:
        logging.warning("타이머가 지연 실행되었습니다.")

    logging.info("WeatherAirDataCollector 시작")

    result = {"collected_at": datetime.utcnow().isoformat() + "Z"}

    for city, cfg in _STATIONS.items():
        weather = _fetch_kma(cfg["nx"], cfg["ny"])
        air     = _fetch_air(cfg["air_station"])
        result[city] = {"weather": weather, "air": air}
        logging.info(f"[{city}] weather={weather} | air={air}")

    _send_to_eventhub(result)
    logging.info("WeatherAirDataCollector 완료")