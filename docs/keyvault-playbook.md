# Key Vault Playbook (Team of 5)

## 목적
- 민감정보(API 키, DB 비밀번호, 토큰)를 Git에서 분리하고 Key Vault로 일원화한다.
- 팀원 5명이 최소한의 절차로 동일하게 운영한다.

## 기본 원칙
- 코드/스크립트/샘플 파일에 실제 비밀값을 넣지 않는다.
- 운영 비밀값은 Key Vault만 사용한다.
- 로컬 개발은 `.env`를 사용하고, `.env`는 Git에 올리지 않는다.

## 역할 (최소 운영)
- `Secret Admin` 1명:
  - Key Vault에 시크릿 등록/수정/삭제 담당
  - 권한: `Key Vault Secrets Officer`
- `Developer` 4명:
  - 코드에서 환경변수 이름만 사용
  - Key Vault 직접 수정하지 않음

## 시크릿 네이밍 규칙
- 형식: `kebab-case`
- 예시:
  - `db-dsn`
  - `azure-openai-key`
  - `naver-client-secret`
  - `weather-api-key`

## 시크릿 요청 프로세스
1. 개발자가 이슈/채널에 요청한다.
2. 요청 양식:
   - `환경`: dev/prod
   - `시크릿 이름`: 예) `db-dsn`
   - `용도`: 예) daangn crawler DB 연결
3. Secret Admin이 Key Vault 등록 후 완료 댓글을 남긴다.
4. 팀원은 값이 아니라 "시크릿 이름"으로 코드/설정을 연결한다.

## 로컬 개발 규칙
- `.env`에 로컬 값 저장
- Git ignore 유지:
  - `.env`
  - `.azure/`
  - `local.settings.json`
- 샘플 파일에는 placeholder만 사용

## 운영 연결 규칙 (다음 이슈 범위)
- Function App Managed Identity 활성화
- Managed Identity에 Key Vault 읽기 권한 부여 (`Key Vault Secrets User`)
- App Setting에서 Key Vault reference 사용
  - 예: `DB_DSN=@Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/db-dsn/)`

## 보안 체크리스트
- 신규 키 발급 시 기존 키 폐기(rotate) 여부 확인
- PR 전 테스트 실행:
  - `python -m unittest discover -s tests/unit -p 'test_*.py' -v`
- 하드코딩 시크릿 검증 테스트 통과 확인:
  - `test_no_hardcoded_secret_literals_in_repo_files`

## 장애 대응
- 키 유출 의심 시 즉시 키 재발급 + 구키 폐기
- 영향 서비스(함수/배치) 재시작 후 정상 동작 확인
- 이슈에 "발생 시각, 영향 범위, 조치 시간" 기록
