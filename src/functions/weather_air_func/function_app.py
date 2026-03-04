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
WEATHER_API_URL  = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
MISE_API_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
EVENTHUB_NAME = "weather-air-stream"

# 수원·용인 기상청 격자 좌표 및 에어코리아 측정소명
_STATIONS = {
    "suwon":  {"nx": 61, "ny": 121, "air_station": "신풍동"},
    "yongin": {"nx": 62, "ny": 120, "air_station": "수지"},
}

# 로컬: local.settings.json / Azure: App Settings (KV Reference)
WEATHER_API_KEY    = os.getenv("WEATHER_API_KEY", "")
MISE_API_KEY       = os.getenv("MISE_API_KEY", "")
EVENT_HUB_CONN_STR = os.getenv("EVENT_HUB_CONN_STR", "")

# ==============================================================================
# 기상청 초단기실황 조회
# ==============================================================================
def _fetch_WEATHER(nx: int, ny: int) -> dict | None:
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
        resp = requests.get(WEATHER_API_URL, params=params, timeout=5)
        resp.raise_for_status()
        header = resp.json()["response"]["header"]
        if header["resultCode"] != "00":
            logging.warning(f"[WEATHER] API 오류: {header['resultCode']} - {header['resultMsg']}")
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
        logging.warning(f"[WEATHER] 호출 실패 nx={nx} ny={ny}: {e}")
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
def _send_event(producer: EventHubProducerClient, payload: dict, partition_key: str) -> None:
    """열려 있는 producer로 단일 이벤트를 전송.

    Args:
        producer: 외부에서 생성된 EventHubProducerClient (연결 재사용)
        payload: 전송할 데이터 딕셔너리
        partition_key: Event Hub 파티션 키 (도시명). 같은 키는 같은 파티션으로 라우팅됨.
    """
    batch = producer.create_batch(partition_key=partition_key)
    batch.add(EventData(json.dumps(payload, ensure_ascii=False)))
    producer.send_batch(batch)
    logging.info(f"[EventHub] 전송 완료: {EVENTHUB_NAME} (partition_key={partition_key})")


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

    collected_at = datetime.utcnow().isoformat() + "Z"
    failed_cities = []

    # Producer 연결은 루프 전체에서 한 번만 열어 재사용
    with EventHubProducerClient.from_connection_string(
        conn_str=EVENT_HUB_CONN_STR,
        eventhub_name=EVENTHUB_NAME,
    ) as producer:
        for city, cfg in _STATIONS.items():
            try:
                weather = _fetch_WEATHER(cfg["nx"], cfg["ny"])
                air     = _fetch_air(cfg["air_station"])
                logging.info(f"[{city}] weather={weather} | air={air}")

                payload = {
                    "city":         city,
                    "collected_at": collected_at,
                    "weather":      weather,
                    "air":          air,
                }
                _send_event(producer, payload, partition_key=city)
            except Exception as e:
                # 한 도시 실패가 다른 도시 수집을 막지 않도록 예외를 격리
                logging.error(f"[{city}] 처리 실패 (스킵): {e}")
                failed_cities.append(city)

    if failed_cities:
        logging.warning(f"WeatherAirDataCollector 완료 — 실패 도시: {failed_cities}")
    else:
        logging.info("WeatherAirDataCollector 완료")