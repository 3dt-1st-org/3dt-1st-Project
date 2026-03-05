import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
import aiohttp
import azure.functions as func
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient

# ==============================================================================
# 상수
# ==============================================================================
WEATHER_API_URL  = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
MISE_API_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
EVENTHUB_NAME = "weather-air-stream"

# 동시에 실행할 최대 API 호출 수 (공공데이터포털 Rate Limit 대응)
# 환경변수 FETCH_CONCURRENCY 로 운영 중 튜닝 가능
CONCURRENCY = int(os.getenv("FETCH_CONCURRENCY", "10"))

# 도시별 기상청 격자 좌표 및 에어코리아 측정소명은 stations.json으로 분리 관리
def _load_stations() -> list[dict]:
    """function_app.py 와 같은 디렉터리의 stations.json을 읽어 리스트로 반환.

    배포 환경에서도 __file__ 기준 절대 경로를 사용하므로 zip deploy, Consumption Plan 모두 안전.
    """
    stations_path = os.path.join(os.path.dirname(__file__), "stations.json")
    with open(stations_path, encoding="utf-8") as f:
        return json.load(f)


# 로컬: local.settings.json / Azure: App Settings (KV Reference)
# .strip()으로 Key Vault 참조 해석 시 혼입될 수 있는 \r\n 제거
WEATHER_API_KEY    = os.getenv("WEATHER_API_KEY", "").strip()
MISE_API_KEY       = os.getenv("MISE_API_KEY", "").strip()
EVENT_HUB_CONN_STR = os.getenv("EVENT_HUB_CONN_STR", "").strip()

# ==============================================================================
# 기상청 초단기실황 조회 (비동기)
# ==============================================================================
KST = timezone(timedelta(hours=9))

async def _fetch_weather(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    nx: int,
    ny: int,
) -> dict | None:
    """기상청 초단기실황 API 비동기 호출 → T1H·RN1·PTY·WSD 추출.

    Args:
        session: 호출 전체에서 공유되는 aiohttp.ClientSession
        sem: 동시 호출 수를 CONCURRENCY 이하로 제한하는 Semaphore
        nx, ny: 기상청 격자 좌표
    """
    # 기상청 API는 ~10분 지연 → KST 기준 1시간 전 기준시 사용
    now = datetime.now(KST) - timedelta(hours=1)
    params = {
        "pageNo":     "1",
        "numOfRows":  "1000",
        "dataType":   "JSON",
        "base_date":  now.strftime("%Y%m%d"),
        "base_time":  now.strftime("%H00"),
        "nx":         nx,
        "ny":         ny,
        "serviceKey": WEATHER_API_KEY,
    }
    timeout = aiohttp.ClientTimeout(total=10)  # 10초 초과 시 독립 실패 처리
    try:
        async with sem:  # Semaphore: 최대 CONCURRENCY개 요청만 동시에 진입
            async with session.get(WEATHER_API_URL, params=params, timeout=timeout) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

        header = data["response"]["header"]
        if header["resultCode"] != "00":
            logging.warning(f"[WEATHER] API 오류: {header['resultCode']} - {header['resultMsg']}")
            return None

        items = {i["category"]: i["obsrValue"]
                 for i in data["response"]["body"]["items"]["item"]}
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
# 에어코리아 대기오염정보 조회 (비동기)
# ==============================================================================
async def _fetch_air(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    station_name: str,
) -> dict | None:
    """에어코리아 API 비동기 호출 → PM10·PM2.5 추출.

    Args:
        session: 호출 전체에서 공유되는 aiohttp.ClientSession
        sem: 동시 호출 수를 CONCURRENCY 이하로 제한하는 Semaphore
        station_name: 에어코리아 측정소명
    """
    params = {
        "serviceKey":  MISE_API_KEY,
        "returnType":  "json",
        "pageNo":      "1",
        "numOfRows":   "1",
        "stationName": station_name,
        "dataTerm":    "DAILY",
        "ver":         "1.3",
    }
    timeout = aiohttp.ClientTimeout(total=10)  # 10초 초과 시 독립 실패 처리
    try:
        async with sem:  # Semaphore: 최대 CONCURRENCY개 요청만 동시에 진입
            async with session.get(MISE_API_URL, params=params, timeout=timeout) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

        items = data.get("response", {}).get("body", {}).get("items", [])
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
# 도시 단위 수집 코루틴 (장애 격리)
# ==============================================================================
async def _collect_city(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    station: dict,
    collected_at: str,
) -> dict | None:
    """단일 도시의 기상·대기 데이터를 병렬로 수집하여 페이로드 딕셔너리로 반환.

    - _fetch_weather / _fetch_air 를 asyncio.gather 로 동시 실행 (도시당 2회 API 호출 동시 처리)
    - 어느 한쪽이 None 을 반환해도 페이로드에 포함 (부분 데이터 허용)
    - 예외 발생 시 logging.error 후 None 반환 → 호출부에서 failed_cities 집계
    - 다른 도시의 수집에 절대 영향을 주지 않는 독립 실행 단위
    """
    city = station["city"]
    try:
        # 기상 + 대기 2개 API 를 동시에 던지고 둘 다 완료될 때까지 대기
        weather, air = await asyncio.gather(
            _fetch_weather(session, sem, station["nx"], station["ny"]),
            _fetch_air(session, sem, station["air_station"]),
        )
        logging.info(f"[{city}] weather={weather} | air={air}")
        return {
            "city":         city,
            "collected_at": collected_at,
            "weather":      weather,
            "air":          air,
        }
    except Exception as e:
        logging.error(f"[{city}] 수집 실패 (스킵): {e}")
        return None


# ==============================================================================
# Event Hubs 비동기 배치 전송
# ==============================================================================
async def _send_events_batched(results: list[dict]) -> None:
    """수집된 모든 도시 페이로드를 도시별 배치로 묶어 동시에 전송.

    - AsyncEventHubProducerClient 를 async with 로 단 1회 생성·공유 (자동 close 보장)
    - 도시별로 create_batch(partition_key=city) → add → send_batch 코루틴을 생성
    - asyncio.gather 로 모든 도시 배치를 동시에 전송 → 네트워크 왕복(RTT) 최소화
    - EventDataBatch 1MB 한도에 단일 도시 페이로드가 초과할 일은 없으나,
      향후 확장 시 배치 롤오버가 필요하면 이 함수에서만 수정하면 됨
    """
    async with EventHubProducerClient.from_connection_string(
        conn_str=EVENT_HUB_CONN_STR,
        eventhub_name=EVENTHUB_NAME,
    ) as producer:
        async def _send_one(payload: dict) -> None:
            city  = payload["city"]
            # 도시마다 독립 배치 생성 → partition_key=city 로 동일 도시는 동일 파티션 보장
            batch = await producer.create_batch(partition_key=city)
            batch.add(EventData(json.dumps(payload, ensure_ascii=False)))
            await producer.send_batch(batch)
            logging.info(f"[EventHub] 전송 완료: {EVENTHUB_NAME} (partition_key={city})")

        # 모든 도시 배치를 동시에 전송 — 각 _send_one 은 독립적으로 실패 가능
        await asyncio.gather(*[_send_one(p) for p in results], return_exceptions=True)


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
async def WeatherAirDataCollector(myTimer: func.TimerRequest) -> None:
    """3시간 간격 타이머 트리거 진입점.

    Azure Functions Python v2 런타임이 네이티브 async 함수를 직접 실행하므로
    asyncio.run() 래퍼 불필요. 코루틴 실행은 Functions 이벤트 루프가 담당.
    """
    if myTimer.past_due:
        logging.warning("타이머가 지연 실행되었습니다.")

    t_start = time.monotonic()
    logging.info("WeatherAirDataCollector 시작")

    collected_at = datetime.now(timezone.utc).isoformat()
    failed_cities: list[str] = []

    stations = _load_stations()
    logging.info(f"수집 대상: {len(stations)}개 도시 | 동시 호출 한도: {CONCURRENCY}")

    sem = asyncio.Semaphore(CONCURRENCY)
    async with aiohttp.ClientSession() as session:
        # 모든 도시를 동시에 실행 — 각 _collect_city 가 내부 예외를 흡수하므로
        # return_exceptions 불필요. 결과는 stations 와 동일한 순서로 반환.
        raw: list[dict | None] = await asyncio.gather(
            *[_collect_city(session, sem, s, collected_at) for s in stations]
        )

    # None 인 항목 = 수집 실패 도시
    results = [r for r in raw if r is not None]
    failed  = [s["city"] for s, r in zip(stations, raw) if r is None]
    failed_cities.extend(failed)

    # 수집 성공 도시를 비동기 배치 전송 — producer 1회 연결, 모든 도시 동시 전송
    if results:
        await _send_events_batched(results)

    elapsed = time.monotonic() - t_start
    total   = len(stations)
    success = total - len(failed_cities)
    if failed_cities:
        logging.warning(
            f"✅ WeatherAirDataCollector 완료 | 성공: {success}/{total} | 실패: {failed_cities} | 소요: {elapsed:.1f}s"
        )
    else:
        logging.info(
            f"✅ WeatherAirDataCollector 완료 | 성공: {success}/{total} | 소요: {elapsed:.1f}s"
        )