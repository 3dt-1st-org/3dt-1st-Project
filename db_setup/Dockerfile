# 1. 베이스 이미지 (PostgreSQL 16 + PostGIS)
FROM postgis/postgis:16-3.4

# 2. 복잡한 소스 빌드(make) 없이, 공식 저장소에서 완성된 pgvector를 바로 설치!
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-16-pgvector && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*