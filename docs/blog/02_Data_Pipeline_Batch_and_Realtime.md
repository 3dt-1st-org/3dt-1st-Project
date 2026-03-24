# LALA 프로젝트 2부: 데이터 파이프라인 — 배치와 실시간의 조화

> **시리즈**: Azure + PostgreSQL + pgvector로 RAG 기반 AI 도슨트 서비스 구축하기  
> **분류**: Data Engineering, Azure Functions, Event Hubs, Stream Analytics  
> **작성일**: 2026년 3월 24일  

---

## 들어가며 — 데이터 파이프라인이 AI의 품질을 결정한다

아무리 뛰어난 AI 모델을 사용하더라도, 그 모델에 제공되는 데이터의 품질과 신선도(Freshness)가 낮다면 결과물은 실망스러울 수밖에 없습니다. "쓰레기가 들어가면 쓰레기가 나온다(Garbage In, Garbage Out)"는 데이터 엔지니어링의 오래된 격언은 LLM 시대에도 여전히 유효합니다. 오히려 더 중요해졌다고 볼 수 있습니다.

LALA의 AI 도슨트가 제값을 하려면 두 가지 데이터가 항상 최신 상태로 유지되어야 합니다:

1. **장소의 이야기 데이터** — "사람들이 이 카페에 대해 요즘 뭐라고 하는지" (블로그 리뷰, 커뮤니티 포스트)
2. **지금 이 순간의 환경 데이터** — "지금 밖이 얼마나 더운지, 미세먼지가 나쁜지" (날씨, 대기질)

전자는 하루 단위, 후자는 3시간 단위로 갱신되어야 하는 서로 다른 생명 주기를 가집니다. 또한 전자는 수십 개의 블로그를 크롤링하고 LLM으로 분석하는 무거운 배치 작업인 반면, 후자는 작은 JSON 데이터를 빠르게 가져오는 가벼운 스트리밍 작업입니다. 이 두 가지 성격이 전혀 다른 파이프라인을 하나의 일관된 시스템으로 통합하는 것이 이번 편의 핵심 주제입니다.

---

## 1. 파이프라인 전체 지도 — 배치와 스트리밍의 분리

LALA의 데이터 파이프라인은 성격에 따라 명확히 두 경로로 분리됩니다.

```
┌─────────────────────────────────────────────────────────────────┐
│                    LALA 데이터 파이프라인 전체 지도                │
└─────────────────────────────────────────────────────────────────┘

[BATCH PATH — 배치 경로 (무거운 처리, 예약 실행)]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

당근마켓 (API 크롤링)    Naver Blog API           경기도 관광 공공 데이터
    │ Mon 03:00 KST           │ Daily 02:00 KST          │ (초기 1회 적재)
    ▼                         ▼                          ▼
daangn_weekly_crawler    review_pipeline_func     [SQL DDL 스크립트]
  (Azure Functions)        (Azure Functions)         
    │                         │
    │ 정제 + LLM 처리           │ 리뷰 수집 + LLM 분석 + 임베딩 생성
    ▼                         ▼
daangn.place_mentions_weekly  locallink.attraction_reviews
                               locallink.attraction_details
                               locallink.restaurant_reviews
                               (embedding VECTOR(1536))

[STREAMING PATH — 스트리밍 경로 (가벼운 처리, 이벤트 기반)]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

기상청 KMA API     에어코리아 API
    │ Timer: 0 0 */3 * * *  │
    └──────────┬────────────┘
               ▼
    weather_air_func (Azure Functions)
    [asyncio.gather() 병렬 수집, 세마포어 제어]
               │
               ▼ JSON 이벤트 (partition_key=city_name)
    ┌──────────────────────┐
    │   Azure Event Hubs   │
    │  [weather-air-stream]│
    └──────────┬───────────┘
               │ Consumer Group 구독
               ▼
    ┌──────────────────────────────────┐
    │    Azure Stream Analytics        │
    │    TumblingWindow(minute, 1)     │
    │    TRY_CAST + CASE WHEN 플래그 │
    └──────────┬───────────────────────┘
               ▼
    locallink.realtime_weather_conditions
    (is_rain_snow, is_bad_dust, is_heatwave, is_coldwave, is_strong_wind)
```

이 분리는 단순히 기술적 편의가 아닌 **아키텍처적 철학**에 기반합니다. 무거운 배치 작업이 실시간 스트리밍 파이프라인의 성능에 영향을 주어서는 안 되고, 반대로 스트리밍 장애가 배치 파이프라인을 멈춰서도 안 됩니다. 두 파이프라인은 서로 독립적으로 장애를 처리하고 재시도할 수 있어야 합니다.

---

## 2. Azure Functions — 왜 상시 구동 서버를 포기했는가

파이프라인의 수집 레이어에서 가장 중요한 결정은 **"어디에서 코드를 실행할 것인가"**였습니다. 처음에는 Azure App Service에 상시 구동 서버를 두고, 크론잡(Cron Job)으로 각 수집 스크립트를 실행하는 방식을 검토했습니다. 그러나 최종적으로 **Azure Functions(서버리스)**를 선택했으며, 이 결정은 큰 효과를 가져왔습니다.

### 2.1 워크로드 특성과 서버리스의 궁합

LALA의 수집 작업들을 타임라인으로 펼쳐보면 흥미로운 패턴이 나타납니다:

```
00:00                           12:00                          24:00
  │                               │                               │
  ├──[02:00 KST]──────────────────┤                               │
  │  review_pipeline_func (20~40분)│                               │
  │                               │                               │
  ├──[03:00 KST Mon]──────────────┤                               │
  │  daangn_weekly_crawler (30~60분)│                              │
  │                               │                               │
  ├───[매 3시간]────────┬──────────┼────────┬──────────┬──────────┤
  │  weather_air_func   │          │        │          │          │
  │  (3~5분)            │          │        │          │          │
  │                     │          │        │          │          │
  └─────────────── 나머지 23시간 = 유휴(IDLE) ─────────────────────┘
```

하루 24시간 중 실제 수집 작업이 실행되는 시간은 1~2시간에 불과합니다. 나머지 22~23시간은 서버가 아무것도 하지 않고 유휴 상태로 대기합니다. 만약 상시 구동 서버를 사용한다면, 이 유휴 시간에 대한 컴퓨팅 비용을 고스란히 지불해야 합니다.

Azure Functions의 소비 기반(Consumption Plan) 과금은 **실행 횟수와 실행 시간**에만 비용이 발생합니다. 월 100만 회 실행은 무료이며, 초과분도 100만 회당 $0.20입니다. LALA의 수집 함수들은 하루에 수십 회 실행되므로 사실상 무료에 가까운 비용으로 운영됩니다.

### 2.2 함수별 트리거 설계

각 Azure Function은 워크로드 특성에 맞는 트리거 타입을 사용합니다:

**weather_air_func — Timer Trigger (3시간 간격)**

```python
# src/functions/weather_air_func/function_app.py

import azure.functions as func
import asyncio
import aiohttp
import json

app = func.FunctionApp()

@app.timer_trigger(
    schedule="0 0 */3 * * *",  # 매 3시간마다 (0시, 3시, 6시, ...)
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False
)
async def WeatherAirDataCollector(myTimer: func.TimerRequest) -> None:
    """기상청 + 에어코리아 데이터를 비동기 병렬로 수집하여 Event Hub에 전송"""
    
    # station.json에서 도시별 좌표 정보 로드
    station_data = load_station_config()
    
    # asyncio 세마포어: 최대 10개 동시 HTTP 요청 제어
    semaphore = asyncio.Semaphore(CONCURRENCY)
    
    async with aiohttp.ClientSession() as session:
        # 모든 도시에 대해 날씨 + 대기질 동시 수집
        tasks = [
            _collect_city(session, semaphore, city)
            for city in station_data
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Event Hub로 일괄 전송 (파티션 키 = city_name)
    await send_to_event_hub(results)
```

여기서 `asyncio.gather()`와 세마포어의 조합이 중요합니다. 기상청 API와 에어코리아 API는 서로 다른 URL을 가지므로, 하나의 도시에 대해 두 API를 **동시에** 호출할 수 있습니다. 또한 수원, 용인, 성남 등 여러 도시의 데이터도 병렬로 수집합니다. 세마포어 `CONCURRENCY=10`은 동시 연결 수를 제한하여 공공 API의 속도 제한(Rate Limit)에 걸리지 않도록 보호합니다.

```python
async def _collect_city(session, semaphore, city_info):
    """단일 도시의 날씨 + 대기질을 병렬로 수집"""
    city_name = city_info['city_name']
    
    try:
        # 날씨와 대기질을 동시에 요청 (asyncio.gather)
        weather_data, air_data = await asyncio.gather(
            _fetch_weather(session, semaphore, city_info['nx'], city_info['ny']),
            _fetch_air(session, semaphore, city_info['lat'], city_info['lon'])
        )
        
        return {
            "city": city_name,
            "temperature": weather_data.get('t1h'),       # 기온 (°C)
            "precipitation_amount": weather_data.get('rn1'),  # 강수량 (mm)
            "precipitation_type": weather_data.get('pty'),     # 강수형태 (0/1/2/3)
            "wind_speed": weather_data.get('wsd'),         # 풍속 (m/s)
            "pm10": air_data.get('pm10Value'),             # 미세먼지 (µg/m³)
            "pm25": air_data.get('pm25Value'),             # 초미세먼지 (µg/m³)
            "data_time": air_data.get('dataTime'),
        }
    except Exception as e:
        # 도시별 에러 격리: 하나의 도시 실패가 전체를 막지 않음
        logging.error(f"도시 {city_name} 수집 실패: {e}")
        return None
```

**기상청 API의 특수한 재시도 로직** — 기상청 초단기실황 API는 정시~45분 사이에 데이터가 없는 경우가 있습니다. 이를 해결하기 위해 1시간 전, 2시간 전 데이터를 순차적으로 시도하는 백오프 로직을 구현했습니다:

```python
async def _fetch_weather(session, semaphore, nx, ny):
    """기상청 초단기실황 조회. 데이터 없을 경우 1h, 2h 전으로 자동 재시도"""
    for hours_back in (1, 2):  # 최근 1시간 전 → 2시간 전 순서로 시도
        base_date, base_time = get_kma_datetime(hours_back=hours_back)
        
        async with semaphore:
            async with session.get(KMA_URL, params={
                "serviceKey": KMA_API_KEY,
                "nx": nx, "ny": ny,
                "base_date": base_date,  # YYYYMMDD
                "base_time": base_time,  # HHMM (0100, 0200, ...)
                "dataType": "JSON",
                "numOfRows": 10
            }) as resp:
                data = await resp.json()
                
        items = data.get('response', {}).get('body', {}).get('items', {}).get('item', [])
        if items:  # 데이터가 있으면 파싱 후 반환
            return parse_kma_items(items)
    
    return {}  # 2시간 이전 데이터도 없으면 빈 딕셔너리 반환
```

**daangn_weekly_crawler — Timer Trigger (매주 월요일 새벽 3시)**

```python
@app.timer_trigger(
    schedule="0 0 3 * * 1",  # 매주 월요일(1) 03:00 UTC+9 → UTC 18:00 일요일
    arg_name="timer",
    run_on_startup=False
)
async def DaangnWeeklyCrawler(timer: func.TimerRequest) -> None:
    """당근마켓 커뮤니티에서 지역 명소/맛집 언급 집계"""
    
    # 어드바이저리 락: 동일 작업의 중복 실행 방지
    job_name = "daangn_weekly_crawl"
    lock_key = compute_advisory_lock_key(job_name)  # SHA256 → bigint
    
    async with get_db_connection() as conn:
        # PostgreSQL Advisory Lock 획득 시도
        locked = await conn.fetchval(
            "SELECT pg_try_advisory_lock($1)", lock_key
        )
        if not locked:
            logging.info("다른 인스턴스가 이미 실행 중. 종료.")
            return
        
        try:
            await run_weekly_crawl(conn)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", lock_key)
```

PostgreSQL의 **Advisory Lock**을 사용한 이유는 Azure Functions가 Auto-scale 환경에서 여러 인스턴스로 분산될 수 있기 때문입니다. 배치 크롤링 작업이 두 인스턴스에서 동시에 실행되면 중복 데이터가 삽입되거나 API 할당량이 초과될 수 있습니다. Advisory Lock의 키는 작업명을 SHA256 해시한 후 PostgreSQL의 bigint 범위인 `(1<<63)` 이하로 마스킹하여 유니크한 정수값을 생성합니다.

### 2.3 당근마켓 크롤러의 지능형 장소명 추출

당근마켓 커뮤니티 포스트에서 장소를 추출하는 것은 단순한 키워드 검색보다 훨씬 복잡한 작업입니다. 한국어 구어체에서 장소는 다양한 문맥으로 등장하기 때문입니다:

```python
# src/functions/daangn_weekly_crawler/function_app.py

# 패턴 1: "장소명 맛집/카페/식당" 형태
PLACE_SUFFIX_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9\s]{1,28})"  # 장소명 (1~30자)
    r"\s*(?:맛집|식당|카페|레스토랑|바|펍)",          # 접미 키워드
    re.IGNORECASE
)

# 패턴 2: "추천/소개 → 장소명" 형태
PLACE_NAME_PATTERN = re.compile(
    r"(?:추천|가볼만|소개|다녀온|방문한)\s*(?:장소|곳|스팟)?\s*[:\-]?\s*"
    r"([가-힣A-Za-z][가-힣A-Za-z0-9\s]{1,30})",
    re.IGNORECASE
)

# 노이즈 필터: 추출된 장소명이 실제 장소가 아닌 경우 제거
NOISE_EXACT_MATCHES = {",", ".", "ㅋ", "ㅎ", "ㅠ", "ㅜ", "ㄷ"}
PRODUCT_HINT_TOKENS = ("컵밥", "라면", "과자", "음료", "삼각김밥")  # 상품명
NON_RECOMMENDABLE_SUFFIXES = ("역", "육교", "구청", "도청", "정류장")  # 인프라

def extract_place_names(text: str) -> list[str]:
    """포스트 텍스트에서 장소명 후보 추출 + 노이즈 필터링"""
    candidates = set()
    
    for pattern in [PLACE_SUFFIX_PATTERN, PLACE_NAME_PATTERN]:
        for match in pattern.finditer(text):
            name = match.group(1).strip()
            
            # 노이즈 필터 적용
            if name in NOISE_EXACT_MATCHES:
                continue
            if any(token in name for token in PRODUCT_HINT_TOKENS):
                continue
            if any(name.endswith(suffix) for suffix in NON_RECOMMENDABLE_SUFFIXES):
                continue
            if len(name) < 2 or len(name) > 30:
                continue
            
            candidates.add(name)
    
    return list(candidates)
```

추출된 장소명은 GPT 기반 LLM 정규화 과정을 거칩니다. "스타벅스 광교점", "광교 스타벅스", "스벅(광교)"처럼 동일 장소가 다양한 이름으로 등장하는 경우, LLM이 표준화된 이름으로 통합합니다. 이를 통해 주간 집계 시 동일 장소의 언급 수가 정확하게 합산됩니다.

---

## 3. Azure Event Hubs — 데이터베이스를 지키는 방파제

`weather_air_func`가 수집한 날씨 데이터를 PostgreSQL에 직접 INSERT하는 것이 가장 단순한 방법입니다. 그러나 우리는 그 사이에 **Azure Event Hubs**를 배치했습니다. 이 결정이 가져오는 아키텍처적 이점을 이해하려면 먼저 "직접 쓰기"의 문제점을 살펴봐야 합니다.

### 3.1 데이터베이스 직접 쓰기의 위험성

```
[문제 시나리오: 직접 DB 쓰기]

weather_air_func (여러 인스턴스)
    ├─ Instance A: 수원 데이터 INSERT → DB OK
    ├─ Instance B: 용인 데이터 INSERT → DB OK
    ├─ Instance C: 성남 데이터 INSERT → DB 연결 풀 소진!
    └─ Instance D: 안양 데이터 INSERT → 타임아웃, 데이터 유실!
    
[문제 1] 연결 폭발 (Connection Storm)
  Functions Auto-scale → 동시 인스턴스 수 급증 → DB 연결 풀 소진

[문제 2] 백프레셔 없는 파이프라인
  DB가 느려져도 수집 함수는 계속 데이터를 보냄 → 데이터 유실

[문제 3] 재처리 불가능
  INSERT 실패 시 해당 데이터 영구 소실 (retry 로직 없음)
```

### 3.2 Event Hubs가 해결하는 세 가지 문제

**문제 1: 디커플링 (Decoupling)**

Event Hubs는 생산자(Producer: weather_air_func)와 소비자(Consumer: Stream Analytics) 사이에 완충 지대를 만듭니다. 생산자는 Event Hub에 이벤트를 보내기만 하면 되고, 소비자의 처리 속도와 무관합니다. DB가 일시적으로 느려지더라도 Event Hub의 이벤트 보존 기간(기본 24시간, 최대 7일) 안에서 소비자가 따라잡을 수 있습니다.

```
[Event Hubs 디커플링 아키텍처]

weather_air_func ──▶  Event Hub ──▶  Stream Analytics ──▶  PostgreSQL
     (생산자)           (버퍼)            (소비자)              (최종 저장)

생산자와 소비자가 완전히 분리됨:
  - DB 장애 시: Event Hub에 이벤트 누적 → DB 복구 후 재처리
  - 소비자 지연 시: Event Hub이 이벤트 보존 (최대 7일)
  - 생산자 급증 시: Event Hub이 트래픽 흡수 (DB 보호)
```

**문제 2: 파티션 키 기반 순서 보장**

날씨 데이터는 도시별로 순서가 중요합니다. 수원의 오전 6시 데이터가 오전 9시 데이터보다 늦게 처리되면 최신 날씨 상태가 잘못 기록됩니다. Event Hubs의 파티션 키(`city_name`)를 사용하면 같은 도시의 이벤트가 항상 같은 파티션으로 라우팅되어 순서가 보장됩니다:

```python
# Event Hub 전송 시 파티션 키 지정
async def send_to_event_hub(weather_results: list[dict]):
    producer = EventHubProducerClient.from_connection_string(
        conn_str=EVENTHUB_CONNECTION_STRING,
        eventhub_name="weather-air-stream"
    )
    
    async with producer:
        for result in weather_results:
            if result is None:
                continue
            
            event_data = EventData(json.dumps(result))
            
            # 파티션 키 = 도시명 → 같은 도시 이벤트는 항상 같은 파티션
            await producer.send_event(
                event_data,
                partition_key=result['city']  # e.g., "수원", "용인"
            )
```

**문제 3: 관찰 가능성 (Observability)**

Event Hubs의 메트릭을 통해 파이프라인의 상태를 쉽게 모니터링할 수 있습니다. 들어오는 메시지 수(Incoming Messages), 나가는 메시지 수(Outgoing Messages), Consumer Group 오프셋 지연(Lag) 등을 Azure Monitor에서 실시간으로 확인할 수 있습니다. 이것은 직접 DB 쓰기 방식에서는 얻기 어려운 파이프라인 투명성입니다.

---

## 4. Azure Stream Analytics — 움직이는 데이터를 가공하다

Event Hubs의 이벤트를 그대로 PostgreSQL에 넣을 수 있다면 Stream Analytics는 왜 필요할까요? 두 가지 중요한 이유가 있습니다.

**첫째**, 원시(Raw) 이벤트 데이터는 AI가 바로 활용하기 어렵습니다. 강수형태 코드 `pty=1`이 "비"를 의미한다는 것, `pm10 >= 80`이 "나쁨" 등급임을 알아야 합니다. 이 해석 로직이 각 소비 애플리케이션마다 중복 구현되는 것은 나쁜 설계입니다.

**둘째**, 순간적인 수치보다 **윈도우 단위 집계**가 더 의미 있는 경우가 많습니다. 순간적으로 풍속이 높았다가 바로 낮아지는 경우보다, 1분 또는 30분 평균 풍속이 높게 유지되는 경우가 실제로 강풍 경보를 내릴 기준이 됩니다.

### 4.1 SAQL 쿼리 — 윈도우 집계와 비즈니스 로직 내포

Stream Analytics 작업(`infra/stream_analytics/azure_ops_realtime_kpi.saql`)의 핵심 쿼리를 살펴봅시다:

```sql
-- azure_ops_realtime_kpi.saql
-- 실시간 운영 KPI를 1분 윈도우로 집계

WITH Flattened AS (
    -- 진단 로그의 JSON Array를 개별 레코드로 분해
    SELECT
        -- COALESCE로 대소문자 다른 필드명 처리 (time vs Time)
        CAST(COALESCE(ev.ArrayValue.time, src.time) AS datetime) AS event_time,
        LOWER(
            REGEXMATCH(GetRecordPropertyValue(GetArrayElement(src.records, 0), 'resourceId'),
            '.*/PROVIDERS/(.+)')
        ) AS resource_id,
        GetRecordPropertyValue(ev.ArrayValue, 'properties.appRoleName') AS app_role_name,
        GetRecordPropertyValue(ev.ArrayValue, 'level') AS log_level,
        GetRecordPropertyValue(ev.ArrayValue, 'properties.resultCode') AS status_code
    FROM [raw-monitoring-input] src
    CROSS APPLY GetArrayElements(src.records) AS ev  -- JSON 배열 평탄화
),

Tagged AS (
    -- 애플리케이션 이름으로 서비스 분류
    SELECT
        event_time,
        log_level,
        status_code,
        CASE
            WHEN LOWER(app_role_name) LIKE '%daagn-crawler%'   THEN 'daagn-crawler'
            WHEN LOWER(app_role_name) LIKE '%weather-air-func%' THEN 'weather-air-func'
            WHEN LOWER(app_role_name) LIKE '%lala-db%'          THEN 'lala-db'
            WHEN LOWER(app_role_name) LIKE '%lala%'             THEN 'lala'
            ELSE 'unknown'
        END AS service_name,
        CASE
            WHEN log_level IN ('Error', 'Critical') THEN 'error'
            WHEN log_level = 'Warning'              THEN 'warning'
            ELSE 'info'
        END AS category
    FROM Flattened
    WHERE event_time IS NOT NULL
)

SELECT
    System.Timestamp AS window_end_utc,          -- 1분 윈도우 종료 시각
    service_name,
    category,
    COUNT(*) AS event_count,                     -- 총 이벤트 수
    SUM(CASE WHEN status_code LIKE '5%' THEN 1 ELSE 0 END) AS http5xx_count,   -- 5xx 오류 수
    SUM(CASE WHEN category = 'error'   THEN 1 ELSE 0 END) AS error_count,      -- 에러 수
    SUM(CASE WHEN LOWER(result_type) = 'success' THEN 1 ELSE 0 END) AS success_count  -- 성공 수
INTO [realtime-kpi-output]   -- PostgreSQL 출력 어댑터
FROM Tagged
GROUP BY
    TumblingWindow(minute, 1),   -- 1분 단위 텀블링 윈도우
    service_name,
    category
HAVING COUNT(*) > 0;
```

`TumblingWindow(minute, 1)`은 겹치지 않는 1분 단위 창을 생성합니다. 예를 들어, 14:00:00~14:00:59 사이의 모든 이벤트가 하나의 행으로 집계되어 `window_end_utc = 14:01:00`에 PostgreSQL에 삽입됩니다.

**날씨 데이터를 위한 AI 컨텍스트 플래그 생성** — 날씨 이벤트 처리에는 별도의 쿼리가 적용되어, 수치형 측정값을 AI가 이해하기 쉬운 이진(0/1) 플래그로 변환합니다:

```sql
-- 날씨 데이터 처리용 ASA 쿼리 (개념적 표현)
SELECT
    System.Timestamp AS record_time,
    city AS location,
    AVG(TRY_CAST(temperature AS float)) AS temperature,
    MAX(TRY_CAST(precipitation_type AS bigint)) AS precipitation_type,
    AVG(TRY_CAST(wind_speed AS float)) AS wind_speed,
    AVG(TRY_CAST(pm10 AS float)) AS pm10,
    AVG(TRY_CAST(pm25 AS float)) AS pm25,
    
    -- AI용 이진 플래그: 조건 충족 시 1, 미충족 시 0
    CASE WHEN MAX(TRY_CAST(precipitation_type AS bigint)) IN (1, 2, 3)
         THEN 1 ELSE 0 END AS is_rain_snow,          -- 강수(비/눈/비+눈) 여부
    CASE WHEN AVG(TRY_CAST(pm10 AS float)) >= 80
         THEN 1 ELSE 0 END AS is_bad_dust,           -- 미세먼지 '나쁨' 이상
    CASE WHEN AVG(TRY_CAST(temperature AS float)) >= 33
         THEN 1 ELSE 0 END AS is_heatwave,           -- 폭염 기준 (33°C 이상)
    CASE WHEN AVG(TRY_CAST(temperature AS float)) <= -12
         THEN 1 ELSE 0 END AS is_coldwave,           -- 한파 기준 (-12°C 이하)
    CASE WHEN AVG(TRY_CAST(wind_speed AS float)) >= 14
         THEN 1 ELSE 0 END AS is_strong_wind         -- 강풍 기준 (14m/s 이상)

INTO [weather-conditions-output]
FROM [weather-air-stream]
GROUP BY
    city,
    TumblingWindow(minute, 30)  -- 30분 집계로 노이즈 제거
HAVING COUNT(*) > 0
```

이 플래그들이 `locallink.realtime_weather_conditions` 테이블에 저장되면, RAG 파이프라인에서 곧바로 활용됩니다. AI 도슨트는 "지금 is_rain_snow=1, is_bad_dust=0"을 보고 "오늘은 비가 오니 실내 코스를 추천드릴게요"라는 맥락적 조언을 생성할 수 있습니다.

---

## 5. 배치 파이프라인 심층 탐구 — review_pipeline_func

실시간 파이프라인이 환경 데이터를 처리한다면, 배치 파이프라인은 "장소의 이야기"를 만들어냅니다. `review_pipeline_func`는 매일 새벽 2시에 실행되며, 수집 → 정제 → LLM 분석 → 임베딩 생성 → 저장의 5단계 파이프라인을 수행합니다.

```python
# src/functions/review_pipeline_func/function_app.py

@app.timer_trigger(
    schedule="0 0 17 * * *",  # UTC 17:00 = KST 02:00
    arg_name="timer"
)
async def ReviewPipelineRunner(timer: func.TimerRequest) -> None:
    """관광지/식당 리뷰 수집 → LLM 분석 → 임베딩 생성 배치 실행"""
    
    # 1단계: 분석 대상 관광지 선정 (PostGIS 기반 반경 검색)
    for area in REVIEW_AREAS:  # REVIEW_AREAS: 위경도 + 반경 설정
        async with get_db_connection() as conn:
            attractions = await conn.fetch("""
                SELECT attraction_name, latitude, longitude
                FROM locallink.gyeonggi_attractions
                WHERE ST_DWithin(
                    ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                    $3
                )
            """, area['lng'], area['lat'], area['radius_m'])
        
        # 2단계: 각 관광지별 Naver 블로그 검색 및 LLM 분석
        await run_batch_for_area(attractions)
    
    # 3단계: 식당 리뷰 파이프라인 (별도 처리)
    for restaurant in RESTAURANT_LIST:
        await run_restaurant_pipeline(restaurant)
```

`run_batch_for_area()` 내부의 처리 흐름을 더 자세히 살펴보면:

```python
# src/collectors/load_review_pipeline.py

async def run_batch_for_area(attractions: list[dict]):
    """관광지 리스트에 대해 리뷰 수집 → LLM 분석 → 임베딩 생성"""
    
    for attraction in attractions:
        name = attraction['attraction_name']
        
        # Step 1: Naver 블로그 검색 API 호출
        raw_blogs = await fetch_naver_blogs(query=name, display=10)
        
        # Step 2: HTML 태그 제거 + 광고성 리뷰 필터링
        clean_texts = [
            clean_and_filter_text(blog['description'])
            for blog in raw_blogs
            if clean_and_filter_text(blog['description']) is not None
        ]
        
        if len(clean_texts) < 3:
            # 리뷰 3개 미만: 충분한 데이터 없음, 건너뜀
            logging.warning(f"{name}: 유효 리뷰 부족 ({len(clean_texts)}개)")
            continue
        
        # Step 3: GPT-4로 리뷰 집합 분석 (summary, atmosphere, tips 추출)
        analysis = await analyze_reviews_with_llm(
            attraction_name=name,
            reviews=clean_texts,
            temperature=0.3  # 낮은 temperature: 일관성 있는 분석 결과
        )
        
        # Step 4: 임베딩 생성 (text-embedding-3-small)
        # 배치 API 호출로 비용 및 레이턴시 최적화
        combined_text = f"{name}. {analysis['summary_ko']}. {' '.join(analysis['atmosphere_ko'])}"
        embedding = generate_embeddings(combined_text)  # → 1536-dim list
        
        # Step 5: PostgreSQL UPSERT
        await upsert_attraction_data(name, analysis, clean_texts, embedding)
```

**배치 임베딩 최적화** — Azure OpenAI의 임베딩 API는 한 번 호출할 때 여러 텍스트를 배열로 전달할 수 있습니다. 100개 리뷰를 하나씩 임베딩하면 100번의 API 호출이 필요하지만, `generate_embeddings_batch()`를 사용하면 단 1번으로 처리됩니다:

```python
def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """여러 텍스트를 단일 API 호출로 일괄 임베딩 생성"""
    embedding_client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=EMBEDDING_API_VERSION
    )
    
    try:
        response = embedding_client.embeddings.create(
            model=EMBEDDING_DEPLOYMENT_NAME,  # "text-embedding-3-small"
            input=texts   # 여러 텍스트를 배열로 전달 → 1번 API 호출
        )
        # 순서 보장: response.data는 input 배열과 동일한 순서로 반환
        return [item.embedding for item in response.data]
    except Exception as e:
        logging.error(f"배치 임베딩 생성 실패: {e}")
        return []
```

이 배치 처리 방식은 API 비용을 최대 90%까지 절감할 수 있습니다.

---

## 6. 파이프라인 모니터링 — azure_ops_monitoring_func

파이프라인을 운영할 때 "잘 돌아가고 있는가"를 실시간으로 파악하는 것은 매우 중요합니다. `azure_ops_monitoring_func`는 Azure Resource Manager API, Azure Monitor, Log Analytics를 정기적으로 폴링하여 운영 메트릭을 수집하고 PostgreSQL에 저장합니다. 이 데이터는 Power BI 대시보드를 통해 시각화됩니다.

```python
# src/functions/azure_ops_monitoring_func/function_app.py

@app.function_name("collect_health_metrics")
@app.timer_trigger(
    schedule="0 */5 * * * *",  # 5분마다
    arg_name="timer"
)
def collect_health_metrics(timer: func.TimerRequest):
    """Azure Monitor에서 리소스별 CPU/메모리/요청 수 수집"""
    
    metrics_data = []
    for resource_id in MONITORED_RESOURCES:
        # Azure Monitor API: 5분 집계 메트릭
        metrics = monitor_client.metrics.list(
            resource_id,
            timespan=timedelta(minutes=5),
            interval=timedelta(minutes=1),
            metricnames="CpuPercentage,MemoryPercentage,Requests",
            aggregation="Average"
        )
        metrics_data.append(parse_metrics(resource_id, metrics))
    
    # health_metrics_5m 테이블에 UPSERT
    upsert_health_metrics(metrics_data)
```

---

## 7. 두 파이프라인의 통합 — AI 도슨트로 가는 길

배치 파이프라인과 실시간 파이프라인이 각자의 테이블을 채우고 나면, 최종적으로 iOS 앱의 도슨트 요청이 들어올 때 다음과 같이 통합됩니다:

```sql
-- RAG 컨텍스트 구성 쿼리 (배치 + 실시간 데이터 통합)
SELECT
    -- 배치 파이프라인이 채운 데이터
    a.attraction_name,
    ad.summary_ko,
    ad.atmosphere_ko,
    ad.tips_ko,
    ar.clean_text,
    
    -- 실시간 파이프라인이 채운 데이터
    w.temperature,
    w.is_rain_snow,
    w.is_bad_dust,
    w.is_heatwave,
    w.pm10
    
FROM locallink.gyeonggi_attractions a
JOIN locallink.attraction_details ad USING (attraction_name)
-- 벡터 유사도 순으로 관련 리뷰 상위 5개 선택
LEFT JOIN LATERAL (
    SELECT clean_text, embedding <=> $1 AS dist
    FROM locallink.attraction_reviews
    WHERE attraction_name = a.attraction_name
    ORDER BY dist ASC
    LIMIT 5
) ar ON TRUE
-- 현재 날씨 (가장 최근 레코드)
LEFT JOIN LATERAL (
    SELECT *
    FROM locallink.realtime_weather_conditions
    WHERE location = a.city_county_name
    ORDER BY record_time DESC
    LIMIT 1
) w ON TRUE
WHERE a.attraction_name = $2;
```

이 쿼리 하나가 배치 파이프라인과 실시간 파이프라인의 결과물을 하나의 컨텍스트로 통합합니다. 이것이 PostgreSQL의 강력함이자, 파이프라인 설계의 최종 목적지입니다.

---

## 마치며

이번 편에서는 LALA 데이터 파이프라인의 전체 흐름을 살펴보았습니다. 배치와 실시간을 명확히 분리한 설계, Azure Functions의 서버리스 장점, Event Hubs의 디커플링 역할, Stream Analytics의 스트림 가공이 유기적으로 연결된 구조입니다.

다음 편은 이 시리즈에서 가장 기술적으로 흥미로운 부분입니다. pgvector와 PostGIS를 활용한 RAG 시스템의 실제 구현, 그리고 사용자의 질문이 AI 도슨트의 답변으로 변환되는 전체 추론 파이프라인을 해부합니다.

---

> **이전 편**: [1부 — 프로젝트 배경 및 전체 아키텍처 설계](./01_Background_and_Architecture_Design.md)  
> **다음 편**: [3부 — RAG 시스템 구축과 pgvector 활용기](./03_RAG_and_Pgvector_Implementation.md)
