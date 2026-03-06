# iOS API 명세서 (Flask) - v1

## 1. 문서 정보
- 문서명: iOS API 명세서
- 버전: v1.0
- 최종 수정일: 2026-03-05
- 서비스 범위: Flask (`/api/ios/v1/*`)
- 기준 점검 URL: `https://lala-ios-api-20260305.azurewebsites.net`

## 2. 적용 범위
- 본 문서는 `src/frontend/web/routes/ios_api.py`에 구현된 iOS 전용 API를 정의한다.
- 인증은 앱 전용 API 키(`X-API-Key`)를 사용한다.
- 시간대 기준은 `Asia/Seoul`이다.

## 3. 공통 규칙

### 3.1 인증
- 필수 헤더: `X-API-Key: <ios_api_key>`
- 누락/불일치 시:
```json
{"error":"unauthorized"}
```
- HTTP 상태코드: `401`

### 3.2 공통 오류 응답
- 대부분의 실패 응답 형식:
```json
{"error":"<message>"}
```

### 3.3 콘텐츠 타입
- `GET` 엔드포인트: `application/json`
- `POST /docent/script`: 요청 `application/json`, 응답 `application/json`
- `POST /docent/audio`: 요청 `application/json`, 성공 응답 `audio/mpeg`

## 4. 엔드포인트 상세

## 4.1 GET /api/ios/v1/places

### 목적
- 지도 카드/핀에 표시할 주변 장소 목록을 조회한다.
- `radius` 모드와 `city` 모드를 지원한다.

### Query 파라미터
| 이름 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `lat` | float | 아니오 | `37.2636` | 사용자 위도 |
| `lng` | float | 아니오 | `127.0286` | 사용자 경도 |
| `radius` | int | 아니오 | `3000` | 양수만 허용 |
| `scope` | string | 아니오 | `radius` | `radius` 또는 `city` |
| `city` | string | 아니오 | - | `scope=city`일 때 도시 힌트 |
| `category` | string | 아니오 | `all` | `all`, `attraction`, `restaurant`, `event` |
| `limit` | int | 아니오 | `50` | 서버에서 `1..100`으로 보정 |

### 동작 규칙
- `scope=radius`: 요청 좌표 기준 반경(`radius`) 내 장소 조회
- `scope=city`: 단일 시/군 단위 조회
- `scope=city`에서 `city`가 없으면, 사용자 좌표와 가장 가까운 영업중 음식점 데이터로 도시를 추정
- `category=all`은 카테고리 통합 후 `distance_m` 오름차순 정렬
- `event`는 시/군 중심 근사 좌표를 사용하며 `is_approximate_location=true`
- `event`는 종료일이 지난 데이터 제외 (`event_end_date >= CURRENT_DATE` 또는 `NULL`)

### 성공 응답 (200)
```json
{
  "count": 100,
  "scope": "city",
  "city": "수원시",
  "places": [
    {
      "id": "string",
      "name": "string",
      "name_en": "string",
      "lat": 37.0,
      "lng": 127.0,
      "category": "attraction|restaurant|event",
      "address": "string",
      "address_en": "string",
      "region": "string",
      "region_en": "string",
      "distance_m": 1200,
      "image_url": "https://...",
      "is_approximate_location": false,
      "event_start_date": null,
      "event_end_date": null,
      "event_url": null
    }
  ]
}
```

### 검증 오류
- `400`: 숫자 파라미터 파싱 실패
- `400`: 잘못된 category
- `400`: 잘못된 scope
- `400`: `radius <= 0`

### 인증/서버 오류
- `401`: 인증 실패
- `500`: 서버 내부 오류

## 4.2 GET /api/ios/v1/weather

### 목적
- 사용자 현재 좌표 기준 현재 날씨, 미세먼지, 미래 예보를 조회한다.

### Query 파라미터
| 이름 | 타입 | 필수 | 기본값 |
|---|---|---|---|
| `lat` | float | 아니오 | `37.2636` |
| `lng` | float | 아니오 | `127.0286` |

### 성공 응답 (200)
```json
{
  "temp": "11",
  "icon": "⛅",
  "dust": {
    "pm10": "37",
    "pm25": "26",
    "grade": "normal",
    "grade_ko": "보통"
  },
  "forecast": [
    {"time":"2026-03-05T21:00","temp":"1","icon":"🌧️"}
  ],
  "source": "open-meteo",
  "dust_source": "open-meteo"
}
```

### 예보 생성 규칙
- 과거 시점 데이터는 제외
- 시간별 데이터 중 3시간 간격으로 샘플링
- 최대 12개 반환

### 폴백 규칙
- Open-Meteo 실패 시 KMA(기상청) 레거시 API로 재시도
- 둘 다 실패하면 `502`:
```json
{"error":"...","fallback_error":"..."}
```

### 오류 코드
- `400`: 숫자 파라미터 오류
- `401`: 인증 실패
- `502`: 외부 날씨 소스 실패

## 4.3 POST /api/ios/v1/docent/script

### 목적
- 장소 도슨트 스크립트를 생성하거나 캐시에서 조회한다.

### 요청 바디
```json
{
  "place_id": "string",
  "category": "attraction|restaurant|event",
  "language": "ko|en",
  "mode": "brief|detail"
}
```

### 동작 규칙
- 캐시 테이블: `locallink.docent_script_cache` (존재 시 사용)
- TTL: `604800초` (7일)
- `fallback`으로 생성된 캐시는 재사용하지 않고 다음 요청에서 다시 LLM 시도
- LLM은 최대 2회 재시도 후 실패 시 fallback 스크립트 생성

### 성공 응답 (200)
```json
{
  "place_id": "string",
  "category": "attraction",
  "language": "ko",
  "mode": "brief",
  "script": "string",
  "source": "cache|llm|fallback",
  "generated_at": "2026-03-05T10:00:00+00:00",
  "ttl_sec": 604800
}
```

### 오류 코드
- `400`: 입력값 검증 실패 또는 context 조회 실패
- `401`: 인증 실패
- `500`: 내부 생성 오류

## 4.4 POST /api/ios/v1/docent/audio

### 목적
- 도슨트 스크립트를 Azure Speech TTS로 MP3 오디오 변환한다.

### 요청 바디
```json
{
  "script": "string",
  "language": "ko|en"
}
```

### 성공 응답
- HTTP `200`
- Content-Type: `audio/mpeg`
- 응답 바디: MP3 바이너리 스트림

### 음성 매핑
- `ko` -> `ko-KR-SunHiNeural`
- `en` -> `en-US-JennyNeural`

### 제약 조건
- `script` 필수
- 최대 길이 `6000`자

### 오류 코드
- `400`: 언어값 오류, 스크립트 누락/길이 초과
- `401`: 인증 실패
- `503`: Speech 설정 누락 또는 TTS 업스트림 실패
- `500`: 서버 내부 오류

## 4.5 GET /api/ios/v1/health

### 목적
- iOS 연동 전/후 서버 상태 점검용 헬스체크

### 성공 응답 (200)
```json
{
  "status": "ok|degraded",
  "db": "ok|error",
  "speech": "ok|missing_config",
  "openai": "ok|missing_config"
}
```

### 판정 규칙
- `db`, `speech`, `openai` 중 하나라도 `ok`가 아니면 `status=degraded`

## 5. Places 데이터 계약
| 필드 | 타입 | Nullable | 설명 |
|---|---|---|---|
| `id` | string | 아니오 | iOS/도슨트 연동용 안정 키 |
| `name` | string | 아니오 | 기본(한글/원문) 이름 |
| `name_en` | string | 아니오 | 영문 이름(없으면 `name` 폴백) |
| `lat` | float | 아니오 | 위도 |
| `lng` | float | 아니오 | 경도 |
| `category` | string | 아니오 | `attraction`, `restaurant`, `event` |
| `address` | string | 아니오 | 기본 주소 |
| `address_en` | string | 아니오 | 영문 주소(없으면 `address` 폴백) |
| `region` | string | 아니오 | 시/군 등 지역 라벨 |
| `region_en` | string | 아니오 | 영문 지역 라벨(없으면 `region` 폴백) |
| `distance_m` | int | 예 | 요청 좌표 기준 거리 |
| `image_url` | string | 예 | 정규화된 대표 이미지 URL |
| `is_approximate_location` | bool | 아니오 | 근사 좌표 여부 |
| `event_start_date` | string | 예 | 행사 시작일 (`YYYY-MM-DD`) |
| `event_end_date` | string | 예 | 행사 종료일 (`YYYY-MM-DD`) |
| `event_url` | string | 예 | 행사 원문 URL |

## 6. 운영 참고사항
- 필수 환경변수:
  - `DB_DSN`
  - `IOS_API_KEY`
  - `WEATHER_API_KEY` (레거시 날씨 폴백 경로에서만 사용)
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_KEY`
  - `AZURE_OPENAI_VERSION`
  - `AZURE_OPENAI_DEPLOYMENT_NAME` 또는 `AZURE_OPENAI_DEPLOYMENT`
  - `AZURE_SPEECH_KEY`
  - `AZURE_SPEECH_REGION`
- iOS 권장 호출 정책:
  - 장소: `scope=city` + `city` 힌트 재사용
  - 날씨: 위치 대이동 시에만 갱신 (현재 정책: 10km)

