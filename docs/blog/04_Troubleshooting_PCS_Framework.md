# LALA 프로젝트 4부: 트러블슈팅 — 파이프라인을 멈춘 한글 문자열 "점검중"

> **시리즈**: Azure + PostgreSQL + pgvector로 RAG 기반 AI 도슨트 서비스 구축하기  
> **분류**: Troubleshooting, Stream Analytics, Data Quality, PCS Framework  
> **작성일**: 2026년 3월 24일  

---

## 들어가며 — 트러블슈팅이 아키텍처의 성숙도를 결정한다

완벽한 시스템은 없습니다. 아무리 정교하게 설계된 파이프라인이라도, "예상치 못한 데이터"가 유입되는 순간 시스템은 침묵하거나 잘못된 정보를 내뱉습니다. 그 순간에 어떻게 반응하느냐가 엔지니어의 실력을 증명합니다.

이번 편은 LALA 프로젝트를 구축하면서 실제로 마주쳤던 트러블슈팅 경험들을 P-C-S(Problem - Cause - Solution) 프레임워크로 기록합니다. 이 프레임워크는 단순히 "어떻게 고쳤다"를 넘어, **"왜 문제가 발생했고, 어떤 논리적 과정으로 원인을 찾았으며, 해결책이 왜 그것이어야 했는가"** 를 설명하는 데 집중합니다.

---

## 케이스 1: 파이프라인을 멈춘 "점검중"

이것은 LALA 개발 과정에서 가장 극적인 트러블슈팅 순간이었습니다. 날씨 데이터가 정상적으로 수집되던 어느 날 오전, PostgreSQL에 신규 데이터가 더 이상 적재되지 않는 것을 발견했습니다.

### Problem (P) — 현상: 파이프라인 셧다운

날씨 데이터 파이프라인의 동작 상황을 모니터링하던 중 다음 이상 징후들이 포착되었습니다:

1. **Azure Functions 실행 로그**: `weather_air_func`는 정상 실행되어 Event Hub로 데이터를 전송하고 있었습니다.
2. **Event Hubs 메트릭**: 메시지 수신(Incoming) 카운터는 정상적으로 증가했습니다.
3. **Stream Analytics 작업 모니터**: 입력 이벤트는 정상 수신되었지만, **출력 이벤트 수가 특정 시점부터 0에 가까워졌습니다**.
4. **PostgreSQL `realtime_weather_conditions` 테이블**: 해당 시간대의 신규 레코드가 삽입되지 않고 있었습니다.

```
[문제 발생 타임라인]

09:00  → ASA 입력: 8개 도시 날씨 이벤트 정상 수신
09:00  → ASA 출력: 8개 레코드 PostgreSQL 적재 성공

10:00  → ASA 입력: 8개 도시 날씨 이벤트 정상 수신
10:00  → ASA 출력: 0개 레코드 (!)

11:00  → ASA 입력: 8개 도시 날씨 이벤트 정상 수신
11:00  → ASA 출력: 0개 레코드 (!)

ASA 진단 로그에 오류 발생:
"Input message type error: Cannot cast value '점검중' to type FLOAT for column 'pm10'"
```

PostgreSQL에서 스키마를 확인했습니다:

```sql
-- locallink.realtime_weather_conditions 테이블 정의
CREATE TABLE locallink.realtime_weather_conditions (
    id SERIAL PRIMARY KEY,
    location VARCHAR(50) NOT NULL,
    record_time TIMESTAMPTZ NOT NULL,
    temperature DOUBLE PRECISION,      -- 기온
    precipitation_type BIGINT,         -- 강수형태
    wind_speed DOUBLE PRECISION,       -- 풍속
    pm10 BIGINT,                       -- 미세먼지 ← 문제 발생 컬럼
    pm25 BIGINT,                       -- 초미세먼지
    is_rain_snow BIGINT,
    is_bad_dust BIGINT,
    ...
);
```

`pm10`은 `BIGINT` 타입입니다. 그런데 에어코리아 API에서 `"pm10": "점검중"` 이라는 문자열이 왔습니다.

---

### Cause (C) — 원인: 공공 데이터의 불완전성과 이기종 시스템 간 자료형 충돌

원인을 추적하는 과정은 마치 탐정 소설의 한 장면 같았습니다. 단서는 세 가지였습니다.

**단서 1: 에어코리아 API 응답 분석**

에어코리아(한국환경공단) OpenAPI는 공공 데이터 포털을 통해 제공됩니다. 대부분의 경우 JSON 응답의 `pm10Value` 필드는 숫자 또는 숫자 형태의 문자열("37")이 옵니다. 그러나 API 문서를 자세히 읽어보니 다음 항목이 있었습니다:

```
- pm10Value: 미세먼지 농도 (µg/m³)
  - 정상: "37" 형태의 숫자 문자열
  - 기기 점검 중: "점검중"
  - 데이터 없음: "-"
  - 오류: "통신장애"
```

공공 API는 하나의 필드에 **숫자형 값, "점검중", "-", "통신장애"** 라는 이질적인 4가지 형태의 값을 혼용합니다. 이것은 공공 데이터의 전형적인 불완전성 패턴입니다. 민간 API처럼 null, 0, undefined 같은 일관된 빈 값 표현이 아니라, 인간이 읽기 위한 한국어 문자열이 기계 처리 파이프라인에 그대로 유입됩니다.

**단서 2: 에러가 ASA에서 발생한 이유**

```
Weather Functions → Event Hub → Stream Analytics → PostgreSQL
                                      ↑
                           에러 발생 지점 (CAST 실패)
```

`weather_air_func`가 에어코리아 API에서 받은 `"점검중"` 값을 그대로 JSON에 담아 Event Hub로 전송했습니다. Event Hub는 단순 메시지 브로커라 자료형을 검사하지 않으므로 "점검중"도 정상적으로 전달됩니다.

문제는 Stream Analytics에서 발생했습니다. ASA는 이 JSON 값을 직접 PostgreSQL의 `BIGINT` 컬럼에 쓰려고 `CAST` 연산을 수행했고, `CAST("점검중" AS BIGINT)`는 예외를 발생시켰습니다. 더 심각한 것은, ASA의 기본 동작이 **CAST 실패 시 해당 레코드 전체를 드롭(Drop)**하는 것이었습니다. 에러 로그에는 기록되지만, 그 레코드는 조용히 사라집니다.

**단서 3: 왜 모든 도시가 아닌 특정 시간대에만 발생했나**

에어코리아 측정소는 정기 점검 일정이 있습니다. 특정 측정소가 점검 중일 때만 "점검중"이 반환되므로, 이 문제는 **항상 발생하지 않고 특정 시간대에만 간헐적으로** 나타났습니다. 개발 환경에서 테스트할 때는 측정소가 정상 운영 중이어서 발견하지 못했고, 프로덕션 환경에서 실제 점검 시간대가 되어서야 드러난 것입니다.

이것이 **공공 API를 사용하는 파이프라인의 근본적인 위험성**입니다. "대부분의 경우엔 잘 됩니다"는 "항상 됩니다"가 아닙니다.

---

### Solution (S) — 해결: TRY_CAST + CASE WHEN 2단계 방어

원인을 파악한 후, 해결책을 두 단계로 설계했습니다.

**1단계: TRY_CAST로 안전한 형 변환 — NULL 반환 전략**

Azure Stream Analytics의 `TRY_CAST` 함수는 형 변환에 실패하면 예외를 던지지 않고 `NULL`을 반환합니다. 이것이 `CAST`와의 핵심 차이입니다:

```sql
-- 기존 코드 (위험): 형 변환 실패 시 전체 레코드 드롭
SELECT CAST(pm10 AS BIGINT) AS pm10 FROM input

-- 개선된 코드 (안전): 형 변환 실패 시 NULL 반환 (레코드 유지)
SELECT TRY_CAST(pm10 AS BIGINT) AS pm10 FROM input
```

`TRY_CAST`를 적용하면 "점검중", "-", "통신장애" 등 숫자로 변환 불가한 값들은 모두 `NULL`이 됩니다. 레코드 자체는 살아남아 그대로 PostgreSQL에 적재됩니다. `NULL`이 적재된 레코드는 날씨 조건 판단 시 "데이터 없음"으로 처리되어 기본값(정상 날씨)을 사용하게 됩니다.

**2단계: CASE WHEN으로 AI용 이진 플래그 생성 — 데이터 품질 강화**

TRY_CAST로 NULL 안전성을 확보한 후, 두 번째 단계는 AI가 직접 활용할 수 있는 형태로 2차 가공하는 것입니다:

```sql
-- Stream Analytics 쿼리 (날씨 스트림 처리)
-- TRY_CAST + CASE WHEN 2단계 방어 로직 완성

SELECT
    System.Timestamp AS record_time,
    city AS location,
    
    -- [1단계] TRY_CAST: 숫자 변환 안전 처리 (NULL 반환)
    AVG(TRY_CAST(temperature AS float))         AS temperature,
    MAX(TRY_CAST(precipitation_type AS bigint)) AS precipitation_type,
    AVG(TRY_CAST(wind_speed AS float))          AS wind_speed,
    AVG(TRY_CAST(pm10 AS float))                AS pm10,
    AVG(TRY_CAST(pm25 AS float))                AS pm25,
    
    -- [2단계] CASE WHEN: AI용 이진 플래그 생성
    -- NULL이면 조건 불충족 → 0 반환 (결측값의 보수적 처리)
    
    CASE
        WHEN MAX(TRY_CAST(precipitation_type AS bigint)) IN (1, 2, 3)
        THEN 1 ELSE 0
    END AS is_rain_snow,         -- 강수형태 1=비, 2=비와눈, 3=눈

    CASE
        WHEN AVG(TRY_CAST(pm10 AS float)) >= 80
        THEN 1 ELSE 0
    END AS is_bad_dust,          -- 에어코리아 PM10 '나쁨' 기준 (80µg/m³)

    CASE
        WHEN AVG(TRY_CAST(temperature AS float)) >= 33
        THEN 1 ELSE 0
    END AS is_heatwave,          -- 기상청 폭염 기준 (33°C)

    CASE
        WHEN AVG(TRY_CAST(temperature AS float)) <= -12
        THEN 1 ELSE 0
    END AS is_coldwave,          -- 기상청 한파 기준 (-12°C)

    CASE
        WHEN AVG(TRY_CAST(wind_speed AS float)) >= 14
        THEN 1 ELSE 0
    END AS is_strong_wind        -- 풍속 강풍 기준 (14m/s, 풍력계급 6)

INTO [weather-conditions-output]
FROM [weather-air-stream]
GROUP BY
    city,
    TumblingWindow(minute, 30)
HAVING COUNT(*) > 0;
```

이 쿼리의 설계 원칙을 하나씩 짚어봅니다:

**왜 NULL 대신 0인가?**

`is_bad_dust` 플래그를 생성할 때, `TRY_CAST` 실패로 `pm10`이 `NULL`이 된 경우 `CASE WHEN NULL >= 80 THEN 1 ELSE 0 END`는 `0`을 반환합니다. 이것은 **보수적(Conservative) 처리**입니다. 미세먼지 데이터를 알 수 없을 때 "황사가 없다"고 가정하는 것이 "황사가 심하다"고 가정하는 것보다 덜 해롭습니다. AI 도슨트가 잘못된 날씨 경보를 발생시키는 것이 경보를 누락하는 것보다 사용자 신뢰를 더 크게 훼손합니다.

**왜 30분 윈도우인가?**

운영 KPI 집계의 1분 윈도우와 달리, 날씨 데이터는 30분 윈도우로 집계합니다. 날씨는 초 단위로 급격히 바뀌지 않으며, 순간적인 강풍이나 갑작스러운 소나기가 장시간 지속되는 기상 현상과 동일하게 취급되어서는 안 됩니다. 30분 평균은 일시적인 이상값 노이즈를 제거하고 실질적인 기상 상태를 반영합니다.

**수정 전후 데이터 흐름 비교**:

```
[수정 전 - CAST 사용]

에어코리아 API    → Event Hub   → ASA               → PostgreSQL
"pm10": "점검중"  → 전달 OK     → CAST 실패 예외     → ❌ 레코드 드롭
"pm10": "37"     → 전달 OK     → CAST("37") = 37   → ✅ 적재 성공

결과: 점검중 발생 시간대 데이터 공백 (파이프라인 셧다운)


[수정 후 - TRY_CAST + CASE WHEN 사용]

에어코리아 API    → Event Hub   → ASA                    → PostgreSQL
"pm10": "점검중"  → 전달 OK     → TRY_CAST → NULL       → ✅ NULL로 적재
                               CASE WHEN NULL>=80 → 0   → ✅ is_bad_dust=0
"pm10": "37"     → 전달 OK     → TRY_CAST → 37         → ✅ 37로 적재
                               CASE WHEN 37>=80 → 0     → ✅ is_bad_dust=0

결과: 어떤 형태의 값이 와도 레코드가 살아남음
```

---

## 케이스 2: PostgreSQL Decimal 타입과 IQR 연산 오류 (PR #124)

두 번째 트러블슈팅은 더 미묘한 타입 불일치 문제였습니다. 식당 랭킹 기능을 배포한 후, 특정 조건에서 랭킹 계산이 `TypeError`와 함께 실패하는 현상이 발생했습니다.

### Problem (P) — 현상: TypeError in IQR Calculation

```
ERROR in restaurant_docent.py, line 98, in rank_restaurants
  Q1, Q3 = scores.quantile([0.25, 0.75])
TypeError: ufunc 'isnan' not supported for the input types, 
and the inputs could not be safely coerced to any supported types 
according to the casting rule ''safe''
```

랭킹 알고리즘은 카드 매출 점수(40%)와 당근마켓 언급 점수(60%)를 조합하여 식당 순위를 산출합니다. 이 과정에서 이상치(Outlier)를 처리하기 위해 IQR(Interquartile Range) 기반 클리핑을 사용합니다.

### Cause (C) — 원인: PostgreSQL NUMERIC 타입 → Python Decimal 역직렬화

원인은 PostgreSQL의 `NUMERIC` 타입과 Python의 타입 시스템 사이의 간극이었습니다:

```python
# 문제의 코드
rows = cursor.fetchall()  # PostgreSQL NUMERIC → Python Decimal
df = pd.DataFrame(rows, columns=["restaurant_name", "card_score_raw", "daangn_score_raw"])

# card_score_raw 컬럼에 Python Decimal 객체들이 들어있음
# Decimal('1500000'), Decimal('800000'), ...

# NumPy quantile은 Decimal 타입을 처리하지 못함!
Q1, Q3 = df["card_score_raw"].quantile([0.25, 0.75])
# → TypeError: ufunc 'isnan' not supported
```

`psycopg2`는 PostgreSQL의 `NUMERIC`/`DECIMAL` 타입을 Python의 `decimal.Decimal` 객체로 역직렬화합니다. `Decimal`은 부동소수점 오차 없이 정확한 십진수 연산을 위한 타입입니다. 그러나 NumPy와 Pandas의 통계 함수들(`quantile`, `std`, `mean` 등)은 내부적으로 C의 `double` 타입을 기반으로 작동하며 `Decimal`을 지원하지 않습니다.

이 문제가 개발 환경에서 발견되지 않은 이유는, 개발 DB에 `FLOAT` 타입으로 정의된 임시 테이블을 사용했기 때문입니다. 프로덕션 DB의 정확한 스키마(카드 매출은 금액이라 `NUMERIC(15,2)`로 정의)를 사용하는 단계에서야 드러났습니다.

### Solution (S) — 해결: astype(float) 명시적 형 변환

```python
# src/services/restaurant_docent.py

def rank_restaurants(candidate_names: list[str], cursor) -> list[str]:
    """카드 매출 40% + 당근 언급 60% 가중 랭킹 (IQR 이상치 보정 포함)"""
    
    cursor.execute("""
        SELECT
            r.bizplc_nm AS restaurant_name,
            COALESCE(c.total_amount, 0) AS card_score_raw,     -- NUMERIC 타입
            COALESCE(d.mention_count, 0) AS daangn_score_raw   -- INTEGER 타입
        FROM locallink.gg_restaurant_info r
        LEFT JOIN analytics.card_sales_monthly c USING (bizplc_nm)
        LEFT JOIN daangn.place_mentions_weekly d USING (restaurant_name)
        WHERE r.bizplc_nm = ANY(%s)
    """, (candidate_names,))
    
    rows = cursor.fetchall()
    df = pd.DataFrame(rows, columns=["restaurant_name", "card_score_raw", "daangn_score_raw"])
    
    # [수정 핵심] PostgreSQL Decimal → Python float 명시적 변환
    # pd.to_numeric(..., errors='coerce'): 변환 불가 값은 NaN으로 (안전 처리)
    df["card_score_raw"] = pd.to_numeric(df["card_score_raw"], errors='coerce').fillna(0.0)
    df["daangn_score_raw"] = pd.to_numeric(df["daangn_score_raw"], errors='coerce').fillna(0.0)
    
    # IQR 기반 이상치 클리핑 (이제 정상 작동)
    for col in ["card_score_raw", "daangn_score_raw"]:
        scores = df[col]
        Q1, Q3 = scores.quantile([0.25, 0.75])  # ← 정상 실행
        IQR = Q3 - Q1
        lower_fence = Q1 - 1.5 * IQR
        upper_fence = Q3 + 1.5 * IQR
        df[col] = scores.clip(lower=lower_fence, upper=upper_fence)
    
    # Min-Max 정규화 [0, 1]
    for col in ["card_score_raw", "daangn_score_raw"]:
        min_val = df[col].min()
        max_val = df[col].max()
        if max_val > min_val:
            df[col] = (df[col] - min_val) / (max_val - min_val)
        else:
            df[col] = 0.0
    
    # 가중 점수 계산 (카드 40% + 당근 60%)
    df["final_score"] = df["card_score_raw"] * 0.4 + df["daangn_score_raw"] * 0.6
    
    return df.sort_values("final_score", ascending=False)["restaurant_name"].tolist()
```

**왜 IQR 클리핑이 필요한가?**

카드 매출 데이터는 극단적인 이상치를 포함합니다. 예를 들어, 대형 웨딩홀이나 뷔페는 일반 식당보다 매출이 수십 배 높을 수 있습니다. 이 이상치가 Min-Max 정규화에 그대로 반영되면, 대부분의 일반 식당 점수가 0에 가까워져 카드 매출 요소가 사실상 무의미해집니다. IQR 클리핑은 이 극단값을 완화하여 모든 식당이 공정하게 경쟁하는 환경을 만듭니다.

---

## 케이스 3: 한글 SSML 인코딩 오류 — 소리 없는 도슨트

세 번째 트러블슈팅은 iOS 앱에서 오디오 파일이 재생되지 않는 현상이었습니다.

### Problem (P) — 현상: TTS 응답 400/500 에러

```
POST /api/ios/v1/docent/audio
→ 500 Internal Server Error
→ Azure Speech Service: 400 Bad Request
   "The SSML document is not well-formed."
```

한국어 도슨트 스크립트를 TTS로 변환하는 과정에서 Azure Speech Service가 "SSML 형식 오류"를 반환했습니다.

### Cause (C) — 원인: 한국어 특수문자의 XML 이스케이프 미처리

SSML(Speech Synthesis Markup Language)은 XML 기반입니다. GPT-4o-mini가 생성한 한국어 도슨트 스크립트에는 XML에서 특수 의미를 가지는 문자들이 등장할 수 있습니다:

- `&` → `&amp;`로 이스케이프 필요
- `<` → `&lt;`로 이스케이프 필요
- `>` → `&gt;`로 이스케이프 필요
- `"` → `&quot;`로 이스케이프 필요

예를 들어, "맛집에서 '진짜 & 가짜' 구별하는 법"이라는 스크립트가 생성되었을 때, `&`를 이스케이프하지 않고 SSML에 그대로 삽입하면 XML 파서는 이것을 HTML 엔티티의 시작으로 해석하여 파싱 오류를 발생시킵니다.

추가로 인코딩 문제도 있었습니다. Python 문자열이 기본적으로 Unicode이지만, HTTP 요청 바디를 `str` 타입으로 전송할 때 일부 환경에서 인코딩이 다르게 처리될 수 있었습니다.

### Solution (S) — 해결: html.escape() + UTF-8 명시적 인코딩

```python
# src/services/speech_synthesizer.py

import html
import requests

def synthesize_speech_mp3(script: str, language: str = "ko") -> bytes:
    """도슨트 스크립트를 MP3로 변환 (인코딩 안전 처리 포함)"""
    
    # [핵심 수정] html.escape()로 XML 특수문자 이스케이프
    # &  →  &amp;
    # <  →  &lt;
    # >  →  &gt;
    # "  →  &quot;
    safe_script = html.escape(script)
    
    # 추가 안전 처리: 인코딩 오류 문자 제거
    # encode-decode 라운드트립으로 비정상 유니코드 문자 정리
    safe_script = safe_script.encode('utf-8', 'ignore').decode('utf-8')
    
    ssml_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<speak version="1.0" 
       xmlns="http://www.w3.org/2001/10/synthesis"
       xml:lang="ko-KR">
    <voice name="ko-KR-SunHiNeural">
        <prosody rate="medium" pitch="medium">
            {safe_script}
        </prosody>
    </voice>
</speak>"""
    
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": "application/ssml+xml; charset=utf-8",  # charset 명시
        "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
    }
    
    # 바이너리 전송: str이 아닌 bytes로 명시적 인코딩
    response = requests.post(
        endpoint,
        headers=headers,
        data=ssml_text.encode("utf-8")  # ← 명시적 UTF-8 인코딩
    )
    
    if response.status_code != 200:
        error_detail = response.text[:200]  # 에러 메시지 앞 200자
        raise SpeechSynthesisError(
            f"TTS 실패: status={response.status_code}, detail={error_detail}",
            status_code=502
        )
    
    return response.content
```

---

## 케이스 4: 어드바이저리 락 오버플로우

마지막으로 소개할 케이스는 `daangn_weekly_crawler`의 중복 실행 방지를 위한 Advisory Lock 구현에서 발생한 문제입니다.

### Problem (P) — 현상: Lock 획득 실패

```
ERROR: integer out of range
Query: SELECT pg_try_advisory_lock(9223372036854775808)
```

### Cause (C) — 원인: SHA256 해시값이 bigint 범위 초과

PostgreSQL의 `pg_try_advisory_lock()`은 `bigint` 타입을 키로 받습니다. Python의 SHA256 해시는 256비트 정수이고, bigint는 64비트 부호 있는 정수(`-2^63 ~ 2^63-1`)입니다. SHA256 결과값이 bigint 범위를 훨씬 초과하므로 직접 사용할 수 없었습니다.

### Solution (S) — 해결: 비트 마스킹으로 bigint 범위 내 유니크 키 생성

```python
# src/functions/daangn_weekly_crawler/function_app.py

import hashlib

def compute_advisory_lock_key(job_name: str) -> int:
    """PostgreSQL Advisory Lock용 bigint 키 생성
    
    SHA256 해시를 63비트로 마스킹하여 bigint 양수 범위 내로 정규화.
    동일 job_name은 항상 동일한 키를 반환하므로 분산 환경에서 락 공유 가능.
    """
    hash_bytes = hashlib.sha256(job_name.encode('utf-8')).digest()
    
    # 처음 8바이트를 int로 변환 (big-endian)
    hash_int = int.from_bytes(hash_bytes[:8], byteorder='big')
    
    # 63비트로 마스킹: 1<<63 미만으로 강제 (bigint 양수 범위)
    # 1<<63 = 9,223,372,036,854,775,808 (bigint 최대값 + 1)
    lock_key = hash_int & ((1 << 63) - 1)  # 최상위 비트만 제거
    
    return lock_key

# 사용 예시
lock_key = compute_advisory_lock_key("daangn_weekly_crawl")
# → 예: 4312876543219876543 (bigint 범위 내 결정론적 정수)

# PostgreSQL에서 락 획득
cursor.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
locked = cursor.fetchone()[0]
```

`(1 << 63) - 1`은 이진수로 `0111...111` (63개의 1)이며, 이 값과 AND 연산을 하면 최상위 비트(부호 비트)가 항상 0으로 강제됩니다. 결과적으로 항상 양수 bigint 범위 내의 값이 생성됩니다. SHA256의 특성상 서로 다른 `job_name`은 충돌 없이 서로 다른 키를 생성하므로, 여러 Azure Functions가 동시에 각자의 Job에 대한 락을 가질 수 있습니다.

---

## 트러블슈팅에서 얻은 교훈 — 방어적 파이프라인 설계 원칙

이 네 가지 트러블슈팅 경험은 데이터 파이프라인 설계에 대한 귀중한 교훈을 남겼습니다:

### 원칙 1: 외부 데이터는 언제나 거짓말을 한다

공공 API, 외부 파트너 API, 심지어 내부 시스템 간 인터페이스도 예상과 다른 값을 보낼 수 있습니다. "문서에 숫자라고 쓰여 있어도 문자열이 올 수 있다"는 마음가짐이 필요합니다. `TRY_CAST`처럼 예외 발생 대신 안전한 대안값(NULL)을 반환하는 방어적 변환이 파이프라인의 안정성을 보장합니다.

```
[방어적 파이프라인의 세 가지 레이어]

레이어 1: 수집 단 (Azure Functions)
  - asyncio 세마포어로 API 과부하 방지
  - 도시별 에러 격리 (하나 실패해도 전체 중단 없음)
  - 재시도 로직 (1h전 → 2h전 백오프)

레이어 2: 스트림 처리 단 (Stream Analytics)
  - TRY_CAST: 자료형 불일치 → NULL 안전 변환
  - CASE WHEN: NULL 처리된 플래그 → 보수적 기본값(0)

레이어 3: 애플리케이션 단 (Flask API)
  - pd.to_numeric(errors='coerce'): Decimal→float 안전 변환
  - html.escape(): LLM 출력의 XML 특수문자 이스케이프
  - Fallback 스크립트: LLM 실패 시에도 서비스 중단 없음
```

### 원칙 2: 이기종 시스템 간 타입 매핑을 명시적으로 관리하라

PostgreSQL의 `NUMERIC` = Python의 `Decimal`, 에어코리아의 `"37"` = 숫자처럼 보이는 문자열. 이 암묵적인 타입 변환 규칙들이 예상치 못한 지점에서 문제를 일으킵니다. 데이터가 시스템 경계를 넘을 때마다 **명시적인 형 변환**과 **변환 실패 처리 로직**을 함께 구현해야 합니다.

### 원칙 3: 테스트는 실제 데이터로 해야 한다

개발 환경에서 발견되지 않는 문제들이 프로덕션에서 나타나는 가장 흔한 이유는 테스트 데이터가 실제 운영 데이터의 엣지 케이스를 커버하지 못하기 때문입니다. "정상 케이스"뿐만 아니라 "비정상 케이스", "결측 케이스", "형식 위반 케이스"를 포함한 다양한 테스트 데이터를 구성해야 합니다.

---

## 마치며

이번 편에서 다룬 네 가지 트러블슈팅을 요약하면:

| 케이스 | 문제 | 원인 | 해결 |
|--------|------|------|------|
| 1 | ASA 파이프라인 셧다운 | "점검중" 문자열의 숫자 필드 유입 | `TRY_CAST` + `CASE WHEN` 2단계 처리 |
| 2 | IQR 계산 `TypeError` | PostgreSQL `NUMERIC` → `Decimal` 역직렬화 | `pd.to_numeric(errors='coerce')` |
| 3 | TTS 400 Bad Request | LLM 출력의 XML 특수문자 미이스케이프 | `html.escape()` + UTF-8 명시 인코딩 |
| 4 | Advisory Lock int overflow | SHA256 → bigint 범위 초과 | 63비트 마스킹으로 범위 정규화 |

모든 트러블슈팅의 공통 패턴은 **"경계(Boundary)에서의 실패"**입니다. 데이터가 한 시스템에서 다른 시스템으로 넘어가는 지점 — API에서 함수로, 함수에서 Event Hub로, ASA에서 PostgreSQL로, LLM에서 SSML 엔진으로 — 에서 예상과 다른 일이 일어납니다. 그 경계마다 방어 코드를 심는 것이 성숙한 파이프라인 엔지니어링입니다.

---

> **이전 편**: [3부 — RAG 시스템 구축과 pgvector 활용기](./03_RAG_and_Pgvector_Implementation.md)  
> **다음 편**: [5부 — AI 윤리 및 엔터프라이즈급 보안 적용](./05_AI_Ethics_and_Security.md)
