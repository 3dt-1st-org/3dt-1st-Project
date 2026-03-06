# LALA Business Logic & Phase 4 Refactor Handoff - 2026-03-06

> **이 문서는 `lala-container-deployment-handoff-2026-03-06.md` 이후 진행된**
> **비즈니스 로직 이식(Phase 1-3) + 시크릿 통합 리팩터(Phase 4) + v4 배포 작업의 델타 문서입니다.**

---

## 1. 작업 범위 요약

| Phase | 내용 | 브랜치 |
|-------|------|--------|
| Phase 1 | 도슨트 GPT 프롬프트 이식 (attraction / restaurant) | `feat/business-logic-conn` |
| Phase 2 | 날씨 DB 우선 조회 + open-meteo 폴백 | `feat/business-logic-conn` |
| Phase 3 | `review_pipeline_func` Azure Function 추가 | `feat/business-logic-conn` |
| Phase 4 | DB 연결 vault_manager 통일 + 전 파일 SecretClient 제거 | `feat/business-logic-conn` |
| 배포 | Docker v4 빌드 → ACR push → App Service 업데이트 | — |

---

## 2. Phase별 상세 변경

### Phase 1 — 도슨트 프롬프트 이식

`src/services/attraction_docent.py`, `src/services/restaurant_docent.py` 내부 GPT 프롬프트를
기존 파이프라인 스크립트 수준의 완성도로 재작성.

- 시스템 프롬프트: 관광지/식당 특성에 맞춘 한국어 현장 해설 가이드 톤
- 사용자 메시지: DB에서 조회한 리뷰·설명·태그 데이터를 인젝션
- `get_db_and_llm_resources()` 함수 단순화: DB 비밀번호 제거, `azure_client` 단일 반환

### Phase 2 — 날씨 DB 우선 조회

`src/frontend/web/routes/ios_api.py` 날씨 엔드포인트 수정:

```
조회 순서: realtime_weather_conditions 테이블 (DB) → 없으면 open-meteo API
```

- `WEATHER_DB_ENABLED` env var로 DB 조회 on/off 가능 (기본 `true`)
- 응답 `source` 필드: `"db"` 또는 `"open-meteo"`

### Phase 3 — review_pipeline_func Azure Function

`src/functions/review_pipeline_func/` 신규 추가.

- 트리거: Azure Storage Queue (`review-pipeline-queue`)
- 역할: 크롤링된 리뷰 → LLM 분류 → DB upsert
- 인증: `vault.get_secret(...)` 경유 (하드코딩 없음)

### Phase 4 — 시크릿 통합 (SecretClient 전면 제거)

**수정된 파일 목록:**

| 파일 | 변경 내용 |
|------|-----------|
| `src/collectors/load_restaurant_review.py` | `DefaultAzureCredential`, `SecretClient`, `_get_secret()` 제거 → `vault.get_secret()` |
| `src/collectors/process_attractions.py` | 동일 |
| `src/collectors/process_restaurants.py` | `_get_vault_client()`, `_get_secret()` 전체 제거 → `vault.get_secret()` |
| `src/services/attraction_docent.py` | 동일 + `get_db_and_llm_resources()` 리팩터 |
| `src/services/restaurant_docent.py` | 동일 |
| `scripts/ingest/add_tags_img_in_attraction_descriptions.py` | `DB_CONFIG` dict 제거 → `vault.get_db_dsn()` |
| `scripts/ingest/fetch_tour_descriptions.py` | 동일 |

---

## 3. vault_manager.py 변경 (핵심)

**파일**: `config/vault_manager.py`

### 변경 1 — KV 연결 실패 시 non-fatal

기존에는 `KEY_VAULT_URL` 미설정 또는 인증 실패 시 `raise`로 앱이 죽었습니다.
이제 경고 로그만 출력하고 env var fallback으로 전환합니다.

```python
# 이전
if not self.vault_url:
    raise ValueError("KEY_VAULT_URL이 설정되지 않았습니다.")
```

```python
# 이후
if self.vault_url:
    try:
        self.client = SecretClient(...)
    except Exception as e:
        print(f"[WARN] KV 연결 실패 - env var fallback 전환: {e}")
else:
    print("[INFO] KEY_VAULT_URL 미설정 - env var에서 시크릿 로드")
```

### 변경 2 — get_secret() env var fallback

KV 클라이언트가 없거나 조회 실패 시 환경변수에서 자동 폴백:

```python
# azure-openai-key → AZURE_OPENAI_KEY
env_key = secret_name.upper().replace("-", "_")
val = os.getenv(env_key)
```

**활용 방식:**
- **Azure App Service**: `KEY_VAULT_URL` + Managed Identity → KV에서 직접 조회
- **로컬 Docker**: `KEY_VAULT_URL` 미설정 + `docker.env` → env var fallback

---

## 4. 유닛 테스트 수정

`tests/unit/test_vault_manager.py` 수정 사항:

| 테스트 | 이전 실패 원인 | 수정 내용 |
|--------|---------------|-----------|
| `test_import_succeeds_with_mocked_vault` | `get_vault_manager` mock 대상이 바뀜 | `patch("config.vault_manager.vault", mock_vault)` 로 변경 |
| `test_no_hardcoded_secrets` | `.venv` 디렉터리 오탐 | `_get_target_files()`에서 `.venv`, `__pycache__`, `.python_packages` 제외 |

**결과**: 44/46 → **46/46 PASSED**

---

## 5. 로컬 Docker 실행 방법

### docker.env 생성 (최초 1회)

KV 접근이 가능한 환경(`az login` 완료)에서:

```python
python -c "
import os, sys
os.environ['KEY_VAULT_URL'] = 'https://kv3dt1stteam2dev01.vault.azure.net/'
sys.path.insert(0, '.')
from config.vault_manager import KeyVaultManager
kv = KeyVaultManager()
names = kv.list_secret_names()
lines = []
for s in sorted(names):
    val = kv.get_secret(s)
    if val is not None:
        lines.append(f'{s.upper().replace(\"-\",\"_\")}={val}')
# IOS_API_KEY 별칭 추가 (앱이 직접 읽는 env var명)
ios = next((l.split('=',1)[1] for l in lines if l.startswith('LALA_IOS_API_KEY=')), '')
lines.append(f'IOS_API_KEY={ios}')
open('docker.env', 'w').write('\n'.join(lines) + '\n')
print('완료')
"
```

> `docker.env`는 `.gitignore`에 등록되어 있습니다. 절대 커밋하지 마세요.

### 컨테이너 실행

```bash
docker run -d --name lala-local --env-file docker.env -p 8000:8000 \
  3dt1stteam2acr.azurecr.io/3dt-web:v4

# 헬스 확인
python -c "
import urllib.request, json
key = '<IOS_API_KEY 값>'
req = urllib.request.Request('http://localhost:8000/api/ios/v1/health', headers={'X-API-Key': key})
with urllib.request.urlopen(req) as r:
    print(json.loads(r.read()))
"
```

---

## 6. Azure 인프라 현재 상태

| 리소스 | 값 |
|--------|----|
| App Service 이름 | `lala` |
| 리소스 그룹 | `3dt-1st-team2` |
| URL | `https://lala.azurewebsites.net` |
| ACR | `3dt1stteam2acr.azurecr.io` |
| 현재 이미지 | `3dt-web:v4` |
| Key Vault | `kv3dt1stteam2dev01.vault.azure.net` |

### 라이브 검증 결과 (2026-03-06)

```json
// GET /api/ios/v1/health
{ "db": "ok", "openai": "ok", "speech": "ok", "status": "ok" }

// GET /api/ios/v1/weather?lat=37.2808&lng=127.0152
{ "source": "open-meteo", "temp": "0.4", "icon": "☀️", ... }
```

---

## 7. 현재 git 상태

```
브랜치: feat/business-logic-conn
최신 커밋:
  79079f5  refactor: remove all remaining SecretClient/DefaultAzureCredential (Phase 4 final)
  1268320  test: add local integration validation script
  1757422  feat: add review_pipeline_func Azure Function (Phase 3)
  d0e5f3a  feat: weather DB-first + docent prompt migration (Phase 1+2)
  8a98b6c  refactor: DB connection unified via vault_manager (Phase 4)

원격: origin/feat/business-logic-conn (push 완료)
작업 트리: clean
```

PR 대상: `feat/business-logic-conn` → `dev`

---

## 8. 향후 이미지 재빌드 절차

```bash
# 1) 빌드 (N을 올려서)
docker build -t 3dt1stteam2acr.azurecr.io/3dt-web:v<N> .

# 2) ACR 로그인 + push
az acr login --name 3dt1stteam2acr
docker push 3dt1stteam2acr.azurecr.io/3dt-web:v<N>

# 3) App Service 업데이트
az webapp config container set \
  --name lala \
  --resource-group 3dt-1st-team2 \
  --docker-custom-image-name 3dt1stteam2acr.azurecr.io/3dt-web:v<N>

# 4) 재시작
az webapp restart --name lala --resource-group 3dt-1st-team2
```

> **`appCommandLine`은 항상 비워 두어야 합니다.** (컨테이너 배포 handoff 문서 참조)

---

## 9. 주의 사항

- **`docker.env`를 절대 커밋하지 마십시오.** KV 시크릿 전체가 평문으로 포함됩니다.
- `scripts/validate_local.py`로 Docker 빌드 전 통합 검증 가능합니다 (서버 기동 불필요, Flask test_client 방식).
- `vault_manager.py`의 env var fallback 덕분에 `KEY_VAULT_URL` 없이도 Docker 로컬 실행이 가능합니다.
- 카카오 지도를 사용하려면 [카카오 개발자 콘솔](https://developers.kakao.com) → 앱 → 플랫폼 → Web에 `http://localhost:8000`(로컬) 및 `https://lala.azurewebsites.net`(라이브)을 모두 등록해야 합니다.
