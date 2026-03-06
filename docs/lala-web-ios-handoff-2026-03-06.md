# LALA Web/iOS Handoff - 2026-03-06

이 문서는 다음 작업자(사람/LLM)가 현재 상태를 바로 이어받을 수 있도록 만든 handoff 문서다.

## 1. 현재 운영 상태

- 활성 운영 호스트: `https://lala.azurewebsites.net`
- 중지된 이전 앱: `lala-ios-api-20260305`
- 현재 브랜치: `feat/lala-webapp-parity`
- 최신 웹 배포 상태:
  - Azure deployment id: `f03c3d2b-dba3-4f65-a350-533b6f22e955`
  - status: `RuntimeSuccessful`

## 2. 현재 구조

- 단일 Flask 앱이 web + iOS API를 함께 처리한다.
- iOS 엔드포인트:
  - `/api/ios/v1/places`
  - `/api/ios/v1/weather`
  - `/api/ios/v1/docent/script`
  - `/api/ios/v1/docent/audio`
  - `/api/ios/v1/health`
- web 엔드포인트:
  - `/api/places`
  - `/api/weather`
  - `/api/docent/script`
  - `/api/docent/audio`
- 공통 서비스 계층:
  - `src/frontend/web/services/map_api_service.py`
  - `src/frontend/web/services/docent_api_service.py`

## 3. 이번 작업에서 반영된 핵심 내용

### 3.1 Backend / API

- iOS/web가 공통 서비스 계층을 재사용하도록 정리함
- weather API 개선:
  - 외부 weather / air-quality 호출 병렬화
  - 좌표 기준 TTL 캐시 추가
  - 동일 좌표 동시 요청 dedupe
  - stale weather fallback 유지
  - stale dust fallback 추가
- web weather 응답과 iOS weather 응답 모두 `Cache-Control` 추가
- `docent/script`, `docent/audio` web 엔드포인트 추가

주요 파일:

- `src/frontend/web/routes/ios_api.py`
- `src/frontend/web/routes/main_map.py`
- `src/frontend/web/services/map_api_service.py`
- `src/frontend/web/services/docent_api_service.py`

### 3.2 Web map UI

- iOS와 유사한 onboarding / map / settings 흐름으로 재구성
- map 내부 설정 버튼 제거
- 현재 위치 마커 + 정확도 원 표시
- 오방색 카테고리 처리 적용
- weather pill과 dust 표시 복구
- 카드 레이아웃을 iOS 형태로 다시 정리:
  - 좌측 텍스트
  - 우측 고정 정사각 이미지
  - 고정 크기 카드
  - 주소 제거
  - 텍스트 line clamp 적용
  - 세로 스크롤 제거, 가로 스크롤만 허용

주요 파일:

- `src/frontend/web/static/js/map_logic.js`
- `src/frontend/web/static/css/layout.css`
- `src/frontend/web/templates/map/index.html`
- `src/frontend/web/templates/base.html`
- `src/frontend/web/static/css/theme.css`

### 3.3 Web weather fetch 기준

현재 web weather 갱신 기준은 다음과 같다.

- 최초 진입: 현재 위치 확보 후 강제 fetch
- 현재 위치 버튼 탭: 강제 fetch
- weather 버튼 탭: 필요 시 fetch 후 sheet 열기
- watchPosition 업데이트:
  - 마지막 weather fetch 이후 `10km 이상 이동` 또는
  - 마지막 fetch 이후 `10분 이상 경과`
  - 일 때만 다시 fetch

관련 파일:

- `src/frontend/web/static/js/map_logic.js`

### 3.4 iOS weather 쪽 로컬 수정

다음 수정은 서버가 아니라 iOS 앱 코드 쪽이다.

- `MapRemoteService.swift`
  - weather snapshot 메모리 캐시
  - in-flight request dedupe
- `MainMapViewModel.swift`
  - weather detail 진입 시 불필요한 force refresh 완화
  - weather 실패 후 자동 재시도 추가
  - 실패 좌표 추적 추가
  - 현재 위치 버튼에서 weather 강제 새로고침

관련 파일:

- `src/frontend/ios/LALA/LALA/Services/MapRemoteService.swift`
- `src/frontend/ios/LALA/LALA/ViewModels/MainMapViewModel.swift`

## 4. iOS 날씨 로드 이슈 분석 결과

### 결론

현재 확인한 범위에서 iOS weather 문제의 원인은 서버가 아니다.

### 근거

1. iOS 로컬 설정값은 정상
   - `src/frontend/ios/LALA/LALA/Config/AppConfig.local.plist`
   - `API_BASE_URL = https://lala.azurewebsites.net`
   - `IOS_API_KEY` 존재

2. `AppConfig.local.plist`는 실제 빌드 시 앱 번들에 복사됨
   - `xcodebuild` 로그에서 `CopyPlistFile ... AppConfig.local.plist` 확인

3. 라이브 iOS weather API는 정상 응답
   - `GET https://lala.azurewebsites.net/api/ios/v1/weather?...`
   - `X-API-Key` 포함 시 `200 OK`
   - `temp`, `icon`, `dust`, `forecast` 모두 정상 포함

4. Swift 파싱 계약도 서버 응답과 맞음
   - `MapRemoteService.swift`의 `RemoteWeatherResponse` / `RemoteWeatherDust` / `RemoteWeatherForecast`

### 실제 원인

`MainMapViewModel.reloadWeather(force:)`가 첫 실패 후 재시도 흐름이 약했다.

- 실패 후 `8초 cooldown`만 있고 예약 재시도가 없었음
- `places`는 retry 스케줄이 있는데 `weather`는 없었음
- 현재 위치 버튼도 `forceWeather: false`였음
- 그래서 첫 요청이 타이밍상 한 번 실패하면 `--` 상태로 남을 수 있었음

### 로컬 코드에서 이미 넣은 수정

- weather 실패 후 자동 retry
- 실패 좌표와 현재 좌표 비교 후 충분히 이동하면 즉시 retry 허용
- 현재 위치 버튼에서 weather 강제 reload

## 5. 배포/반영 상태를 구분해서 봐야 하는 것

### 이미 서버에 배포된 것

- web 카드 레이아웃 수정
- web weather/dust fetch 기준 정리
- backend weather cache / stale dust fallback
- web weather API 응답 개선

### 서버 배포로 해결되지 않는 것

- iOS 앱 코드 수정
- iOS weather retry / current-location force refresh

즉:

- `lala` 웹앱은 최신 서버 코드가 반영됨
- iOS weather fix는 앱을 다시 빌드/실행해야 반영됨

## 6. 현재 dirty worktree 상태

이 작업은 아직 커밋하지 않았다.

`git status --short` 기준 주요 변경 파일:

- `scripts/sync_ios_api_base_url_from_keyvault.py`
- `src/frontend/ios/LALA/LALA/Services/MapRemoteService.swift`
- `src/frontend/ios/LALA/LALA/ViewModels/MainMapViewModel.swift`
- `src/frontend/web/routes/ios_api.py`
- `src/frontend/web/routes/main_map.py`
- `src/frontend/web/static/css/layout.css`
- `src/frontend/web/static/css/theme.css`
- `src/frontend/web/static/js/map_logic.js`
- `src/frontend/web/templates/base.html`
- `src/frontend/web/templates/map/index.html`
- `src/frontend/web/routes/onboarding.py`
- `src/frontend/web/routes/settings.py`
- `src/frontend/web/templates/onboarding/*.html`
- `src/frontend/web/templates/settings/index.html`
- `src/frontend/web/services/map_api_service.py`
- `src/frontend/web/services/docent_api_service.py`
- `tests/unit/test_map_api_service.py`
- `tests/unit/test_web_routes_main_map.py`
- `tests/unit/test_docent_api_service.py`

주의:

- `src/frontend/ios/LALA/LALA/Config/AppConfig.local.plist` 는 git ignore 상태다.
- 값은 로컬에만 있으므로, 다른 작업자가 같은 값을 쓰려면 직접 채워야 한다.

## 7. 검증 결과

### 로컬 테스트

실행한 검증:

```bash
node --check src/frontend/web/static/js/map_logic.js
python3 -m py_compile src/frontend/web/routes/ios_api.py src/frontend/web/routes/main_map.py
.venv/bin/pytest -q tests/unit/test_map_api_service.py tests/unit/test_web_routes_main_map.py tests/unit/test_docent_api_service.py
```

결과:

- `pytest`: `16 passed`
- JS syntax: passed
- Python compile: passed

### 라이브 API 확인

검증된 응답:

```bash
curl -sS -H "X-API-Key: <IOS_API_KEY>" \
  "https://lala.azurewebsites.net/api/ios/v1/weather?lat=37.2636&lng=127.0286"
```

확인한 값:

- `temp = 3.4`
- `dust.grade = normal`
- `dust.pm10 = 34`
- `dust.pm25 = 24`
- `forecast[]` 존재

## 8. 이 환경에서 막힌 것

이 Codex 환경에서는 `xcodebuild`가 asset catalog 단계에서 실패한다.

실패 원인:

- `No available simulator runtimes for platform iphonesimulator`

중요:

- 이건 Swift 코드 문법 오류가 아니라 이 환경의 CoreSimulator/ibtool 문제다.
- 빌드 로그상 `AppConfig.local.plist` 복사 단계까지는 정상 확인됨

## 9. 다음 작업자가 바로 해야 할 일

### 가장 우선

1. 실제 iOS 실행 환경(Xcode GUI / 로컬 시뮬레이터 / 실기기)에서 앱 재빌드
2. 첫 진입 시 weather가 `--`가 아닌 값으로 뜨는지 확인
3. 현재 위치 버튼 탭 시 weather/dust가 즉시 갱신되는지 확인
4. weather detail sheet 진입 시 빈값으로 다시 떨어지지 않는지 확인

### 만약 iOS weather가 여전히 실패하면

다음 위치에 디버그 로그를 추가해서 실패 지점을 찍으면 된다.

- `src/frontend/ios/LALA/LALA/ViewModels/MainMapViewModel.swift`
  - `reloadWeather(force:)`
  - `locationManager(_:didUpdateLocations:)`
  - `centerOnUserLocation(animated:)`

- `src/frontend/ios/LALA/LALA/Services/MapRemoteService.swift`
  - `fetchWeather(at:)`
  - `performRequest(url:)`
  - `validate(response:)`

추천 로그 항목:

- `coordinate`
- `force`
- `lastWeatherFetchCoordinate`
- `lastWeatherFailureAt`
- `HTTP status`
- `error.localizedDescription`

### 웹 추가 검증

다음 브라우저 시나리오 확인 권장:

1. `LALA` 타이틀 클릭 없이 첫 진입 시 weather가 뜨는지
2. 현재 위치 버튼 탭 시 weather/dust가 갱신되는지
3. 카드가 긴 이름이어도 고정 크기를 유지하는지
4. 카드 패널이 세로 스크롤되지 않는지
5. weather sheet에서 dust와 forecast가 같이 보이는지

## 10. 참고 문서

- `docs/ios-flask-api-connection.md`
- `docs/ios-api-spec-v1.md`
- `docs/keyvault-playbook.md`

