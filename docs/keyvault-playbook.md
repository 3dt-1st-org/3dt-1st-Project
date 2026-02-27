# 팀원 사용 방법 (Portal only)

## 1) Key Vault 접속
- Azure Portal -> `kv3dt1stteam2dev01` -> `비밀 (Secrets)`

## 2) 값 확인
- 필요한 시크릿 클릭 (`db-dsn`, `naver-client-id` 등)
- `현재 버전` 선택
- `비밀 값 표시`로 값 확인

## 3) 로컬에 넣기
- 각자 `.env` 또는 터미널 환경변수로 붙여넣기
- 예시:
  - `DB_DSN=...`
  - `NAVER_CLIENT_ID=...`
  - `NAVER_CLIENT_SECRET=...`
  - `AZURE_OPENAI_KEY=...`

## 4) 실행
- 같은 터미널 세션에서 스크립트 실행
