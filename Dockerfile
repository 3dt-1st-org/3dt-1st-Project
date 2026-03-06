# Flask 웹앱 컨테이너 이미지
FROM python:3.11-slim

# 시스템 패키지 (psycopg2-binary 빌드 불필요하지만 libpq는 필요)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 복사 (레이어 캐시 활용)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 프로젝트 전체 복사 (src/collectors, config 등 포함)
COPY . .

# Python 경로 명시 (네임스페이스 패키지 인식 보장)
ENV PYTHONPATH=/app

# Azure App Service 기본 포트
EXPOSE 8000

# gunicorn으로 Flask 앱 실행
# wsgi:application 사용 → Azure App Service CMD 따옴표 파싱 문제 우회
# --worker-tmp-dir /tmp : App Service sandbox에서 /app 쓰기 거부 방지
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "1", \
     "--threads", "4", \
     "--worker-class", "gthread", \
     "--timeout", "120", \
     "--worker-tmp-dir", "/tmp", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "wsgi:application"]
