# LALA 컨테이너 배포 Handoff - 2026-03-06

> **이 문서는 `lala-web-ios-handoff-2026-03-06.md` 이후 진행된 컨테이너 배포 작업의 델타(변경·추가) 문서입니다.**
> 이전 문서의 iOS/Web 기능 내용은 유효하며, 이 문서는 배포 방식 변경 사항만 다룹니다.

---

## 1. 변경된 배포 방식

| 항목 | 이전 (handoff 문서 기준) | 현재 |
|------|--------------------------|------|
| 배포 방식 | Azure App Service 코드 배포 (Oryx 빌드) | **컨테이너 배포** (ACR 이미지 pull) |
| 이미지 레지스트리 | 없음 | `3dt1stteam2acr.azurecr.io` |
| 현재 이미지 태그 | — | `3dt-web:v3` (SHA: `sha256:7c84fca5…`) |
| startup command | `appCommandLine`으로 gunicorn 명시 | **Dockerfile CMD** (`wsgi:application`) |
| 인증 | — | System-assigned Managed Identity + AcrPull 역할 |
| 브랜치 | `feat/lala-webapp-parity` (merged) | `feat/container-deployment` |

---

## 2. 근본 원인 (배포 실패 → 성공 경위)

### 증상

App Service 컨테이너 기동 시 exit code 3, 로그:

```
ModuleNotFoundError: No module named '"src
```

### 원인

Azure Portal에서 수동으로 설정했던 `appCommandLine`이 Dockerfile `CMD`를 **완전히 오버라이드**하고 있었습니다.

```
appCommandLine = gunicorn ... "src.frontend.web.app:create_app()"
```

Linux 컨테이너 shell이 이 문자열을 실행할 때 **따옴표를 literal 문자로 그대로 전달**하여
Python이 `"src`라는 모듈 이름으로 파싱 → `ModuleNotFoundError`.

### 해결

1. `wsgi.py` 생성 — `create_app()` callable을 모듈 레벨 객체로 분리
2. `Dockerfile CMD` → `wsgi:application` (따옴표 불필요)
3. `az resource update --set properties.siteConfig.appCommandLine=""`

---

## 3. 새로 추가된 파일

### `wsgi.py` (프로젝트 루트)

```python
"""
Gunicorn entrypoint for Azure App Service.
wsgi.py references avoid quoting/parsing issues with create_app() callable
in Docker CMD on Azure Linux containers.
"""
from src.frontend.web.app import create_app

application = create_app()
```

> **주의**: Azure Portal / `az webapp config` 에서 **startup command(appCommandLine)를 반드시 비워두어야 합니다.**
> 다시 채우면 Dockerfile CMD가 무시되고 동일한 문제가 재현됩니다.

### `Dockerfile` (프로젝트 루트, 신규)

```dockerfile
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["gunicorn",
     "--bind", "0.0.0.0:8000",
     "--workers", "1",
     "--threads", "4",
     "--worker-class", "gthread",
     "--timeout", "120",
     "--worker-tmp-dir", "/tmp",
     "--access-logfile", "-",
     "--error-logfile", "-",
     "--log-level", "info",
     "wsgi:application"]
```

---

## 4. 수정된 파일

### `requirements.txt`

다음 두 패키지 추가:

```
azure-identity>=1.16
azure-keyvault-secrets>=4.8
```

Key Vault SDK가 컨테이너 이미지에 포함되도록 명시했습니다.

### `src/collectors/load_review_pipeline.py`

`fetch_attractions_in_area(lat, lng, radius_m)` 함수를 추가했습니다.  
PostGIS `ST_DWithin` 기반으로 반경 내 관광지를 조회합니다.  
모든 DB 인증 정보는 `vault.get_secret(...)` 경유 — 하드코딩 없음.

---

## 5. Azure 인프라 현재 상태

| 리소스 | 값 |
|--------|----|
| App Service 이름 | `lala` |
| 리소스 그룹 | `3dt-1st-team2` |
| URL | `https://lala.azurewebsites.net` |
| ACR | `3dt1stteam2acr.azurecr.io` |
| 이미지 | `3dt-web:v3` |
| Managed Identity | System-assigned |
| Identity principalId | `b58afd1e-5e87-42ef-a073-f7c1fa4f49d4` |
| AcrPull 역할 스코프 | ACR 리소스 |
| Key Vault Secrets User 스코프 | Key Vault 리소스 |

### `/health` 확인 결과

```json
{ "db": "ok", "openai": "ok", "speech": "ok", "status": "ok" }
```

---

## 6. 현재 git 상태

```
브랜치: feat/container-deployment
최신 커밋: 301cc10 "chore: remove stray git-diff artifact file"
           88c6de9 "feat: containerize Flask app for Azure App Service"
원격: github.com/3dt-1st-org/3dt-1st-Project
작업 트리: clean
```

PR: `feat/container-deployment` → `dev`  
링크: https://github.com/3dt-1st-org/3dt-1st-Project/pull/new/feat/container-deployment

---

## 7. 이미지 재빌드 절차 (향후 변경 시)

```bash
# 1) 이미지 빌드
docker build -t 3dt1stteam2acr.azurecr.io/3dt-web:v<N> .

# 2) ACR 로그인
az acr login --name 3dt1stteam2acr

# 3) push
docker push 3dt1stteam2acr.azurecr.io/3dt-web:v<N>

# 4) App Service 이미지 태그 업데이트
az webapp config container set \
  --name lala \
  --resource-group 3dt-1st-team2 \
  --docker-custom-image-name 3dt1stteam2acr.azurecr.io/3dt-web:v<N>

# 5) 재시작
az webapp restart --name lala --resource-group 3dt-1st-team2
```

> **`appCommandLine`은 수정하지 않습니다.** 비어 있는 상태를 반드시 유지해야 합니다.

---

## 8. 주의 사항

- **Azure Portal에서 "시작 명령(Startup Command)"을 절대 입력하지 마십시오.**  
  입력하면 Dockerfile CMD가 무시되고 `'"src` 오류가 재현됩니다.
- `latest` 태그는 App Service가 캐시를 재사용할 수 있으므로,  
  변경 시 항상 `:v<N>` 식으로 버전 태그를 올려 주십시오.
- `DOCKER_REGISTRY_SERVER_PASSWORD`는 ACR → Managed Identity pull로  
  대체 가능하지만, 현재는 admin key도 병행 설정되어 있습니다.  
  일관성을 위해 추후 admin key를 비활성화하고 Managed Identity 단독으로  
  전환하는 것을 권장합니다.
