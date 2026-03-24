# LALA 프로젝트 3부: RAG 시스템 구축과 pgvector 활용기

> **시리즈**: Azure + PostgreSQL + pgvector로 RAG 기반 AI 도슨트 서비스 구축하기  
> **분류**: RAG, pgvector, PostGIS, Vector Search, LLM, Prompt Engineering  
> **작성일**: 2026년 3월 24일  

---

## 들어가며 — RAG란 무엇이고 왜 필요한가

GPT-4o와 같은 대형 언어 모델(LLM)은 놀라운 텍스트 생성 능력을 갖추고 있지만, 사전 학습(Pre-training) 데이터의 한계라는 근본적인 제약을 가집니다. 모델이 알고 있는 것은 학습 데이터 마감(Knowledge Cutoff) 시점까지의 정보이며, 특정 지역의 소규모 식당이나 최근 개장한 관광지 같은 long-tail 지식은 포함되지 않을 가능성이 높습니다.

이 문제를 해결하는 것이 **RAG(Retrieval-Augmented Generation, 검색 증강 생성)**입니다. 핵심 아이디어는 단순합니다: LLM에게 질문할 때, **관련 문서를 먼저 검색(Retrieval)**하여 그 내용을 프롬프트의 컨텍스트(Context)로 제공하고, 모델은 이 외부 지식을 바탕으로 답변을 **생성(Generation)**합니다.

```
[기존 LLM만 사용 시]
사용자 질문: "광교 호수공원 근처에서 비 오는 날 갈 만한 실내 카페 있어?"
LLM 응답: "광교 호수공원 근처에는 다양한 카페가 있습니다..." (환각, 구체성 없음)

[RAG 시스템 사용 시]
1. Retrieval: 광교 호수공원 관련 최근 블로그 리뷰 5개 검색
               + 현재 날씨 (is_rain_snow=1, 오늘 비 오는 중)
               + 주변 실내 관광지 목록
2. Generation: 검색된 실제 정보를 컨텍스트로 주입
LLM 응답: "지금 비가 오고 있네요! 광교 호수공원 바로 옆 갤러리아 백화점의 
           카페 A는 유리 창가 자리가 유명하고, 최근 방문자 리뷰에서 
           '비 오는 날 아늑한 분위기'로 항상 언급되더라고요." (정확, 구체적)
```

이번 편에서는 LALA의 RAG 시스템이 어떤 기술 스택으로 구성되었으며, 각 기술 선택의 이유와 트레이드오프가 무엇이었는지 상세히 다룹니다.

---

## 1. PostGIS — 위치 기반 서비스의 공간 쿼리 기반

RAG 파이프라인의 가장 첫 단계는 **"사용자 위치 근처"의 후보 장소를 찾는 것**입니다. 이 공간 쿼리를 제대로 구현하려면 지구가 구(球)라는 사실을 고려해야 합니다.

### 1.1 위도/경도 단순 비교의 함정

많은 개발자들이 처음에는 위도/경도의 단순 수치 비교로 거리를 계산합니다:

```sql
-- 잘못된 방법: 위도/경도 차이만으로는 실제 거리가 아님!
SELECT attraction_name
FROM locallink.gyeonggi_attractions
WHERE ABS(latitude - 37.2636) < 0.03    -- 위도 0.03도 ≒ 3.3km (위도 방향)
  AND ABS(longitude - 127.0286) < 0.04  -- 경도 0.04도 ≒ ?km (경도 방향, 위도에 따라 달라짐!)
```

이 방법의 근본적인 문제는 경도 1도의 실제 거리가 위도에 따라 달라진다는 것입니다. 적도에서 경도 1도는 약 111km이지만, 위도 37도(한국)에서는 약 89km입니다. 따라서 경도 차이를 위도 차이와 동일하게 취급하면 수평 방향(동서)으로 최대 20% 이상의 오차가 발생합니다.

### 1.2 PostGIS로 정확한 구면 거리 계산

PostGIS의 `geography` 타입은 WGS84 타원체(지구의 실제 형태 근사치)를 기반으로 정확한 거리 계산을 수행합니다:

```sql
-- 올바른 방법: PostGIS geography 타입으로 정확한 거리 계산

-- 스키마 설정 시 확장 기능 활성화
CREATE EXTENSION IF NOT EXISTS postgis;

-- 위치 테이블 정의 (geography 타입 사용)
CREATE TABLE locallink.locations (
    id SERIAL PRIMARY KEY,
    name_ko VARCHAR(100) NOT NULL,
    geom GEOGRAPHY(Point, 4326),      -- 4326: WGS84 좌표계 (GPS와 동일)
    geofence_radius_m INT NOT NULL    -- 지오펜스 반경 (미터)
);

-- 공간 인덱스 생성 (인덱스 없으면 전체 스캔, 매우 느림!)
CREATE INDEX idx_locations_geom ON locallink.locations USING GIST(geom);

-- 정확한 반경 기반 검색
SELECT
    attraction_name,
    ST_Distance(
        ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography,
        ST_SetSRID(ST_MakePoint(longitude::float, latitude::float), 4326)::geography
    ) AS distance_meters,
    road_address,
    city_county_name
FROM locallink.gyeonggi_attractions
WHERE
    -- ST_DWithin: GIST 인덱스를 활용한 효율적인 반경 필터
    -- 전체 테이블을 스캔하지 않고 인덱스로 후보를 먼저 좁힘
    ST_DWithin(
        ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography,
        ST_SetSRID(ST_MakePoint(longitude::float, latitude::float), 4326)::geography,
        :radius_m  -- 반경 (미터 단위)
    )
ORDER BY distance_meters ASC
LIMIT :top_k;
```

`ST_DWithin`과 `ST_Distance`의 차이를 이해하는 것이 중요합니다:
- `ST_DWithin(a, b, radius)`: 인덱스를 활용하여 **반경 내 점을 빠르게 필터링**. WHERE 절에 사용.
- `ST_Distance(a, b)`: 두 점 사이의 **정확한 거리를 계산**. SELECT 절에서 정렬/표시용.

### 1.3 날씨 조건과 결합한 하이브리드 공간 쿼리

LALA의 가장 독특한 기능 중 하나는 **현재 날씨를 반영한 장소 필터링**입니다. 비가 오는 날에는 실외 관광지를 추천하지 않는 것이죠. 이를 위해 PostGIS 반경 검색과 실시간 날씨 플래그를 결합한 하이브리드 쿼리를 작성했습니다:

```sql
-- sql/analytics/hybrid_place_matching.sql
-- 위치 + 날씨 + 거리를 결합한 스마트 장소 추천 쿼리

WITH
-- Step 1: 현재 날씨 상태 (가장 최신 레코드)
CurrentWeather AS (
    SELECT
        outdoor_status,
        pm10,
        pm25,
        is_rain_snow,
        is_bad_dust,
        is_heatwave,
        is_coldwave,
        is_strong_wind,
        temperature
    FROM locallink.realtime_weather_conditions
    WHERE location = :city           -- 예: '수원'
    ORDER BY record_time DESC
    LIMIT 1
),

-- Step 2: 반경 내 관광지 후보 (PostGIS 반경 필터 + 거리 계산)
AttractionCandidates AS (
    SELECT
        t.tourist_nm AS place_name,
        t.lat,
        t.lng,
        t.is_indoor,                  -- 실내/실외 분류 (GPT-4o-mini 사전 분류)
        ST_Distance(
            ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography,
            ST_SetSRID(ST_MakePoint(t.lng::float, t.lat::float), 4326)::geography
        ) AS distance_meters
    FROM locallink.tourist_spot_info t
    WHERE
        t.lat IS NOT NULL
        AND t.lng IS NOT NULL
        AND ST_DWithin(                -- GIST 인덱스 활용
            ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography,
            ST_SetSRID(ST_MakePoint(t.lng::float, t.lat::float), 4326)::geography,
            :radius_m
        )
),

-- Step 3: 날씨 조건 기반 필터링
AttractionFiltered AS (
    SELECT ac.*
    FROM AttractionCandidates ac
    CROSS JOIN CurrentWeather cw
    WHERE
        CASE
            -- 나쁜 날씨 (비, 눈, 황사, 폭염 중 하나 이상): 실내 장소만 통과
            WHEN (
                cw.is_rain_snow = 1
                OR cw.is_bad_dust = 1
                OR cw.pm10 > 80
                OR cw.temperature > 33
            )
            THEN ac.is_indoor = TRUE
            -- 좋은 날씨: 모든 장소 통과
            ELSE TRUE
        END
)

-- Step 4: 거리순 정렬, Top-K 반환
SELECT
    place_name,
    distance_meters AS distance_m,
    is_indoor,
    lat,
    lng
FROM AttractionFiltered
ORDER BY distance_meters ASC
LIMIT :top_k;
```

이 쿼리는 단순한 SELECT가 아닙니다. PostGIS의 공간 인덱스, 실시간 날씨 플래그, 장소의 실내/외 분류가 결합된 **상황 인식(Context-aware) 추천 쿼리**입니다. 여기서 `is_indoor` 값은 별도의 분류 파이프라인(`scripts/ingest/classify_tourist_indoor.py`)에서 GPT-4o-mini를 사용하여 사전에 분류된 값입니다.

---

## 2. 텍스트 임베딩 — 의미를 숫자로 변환하는 과정

PostGIS가 "어디"를 처리한다면, pgvector는 "무엇을"을 처리합니다. 사용자의 자연어 질문과 수천 개의 블로그 리뷰 사이의 **의미적 유사도(Semantic Similarity)**를 계산하기 위해 텍스트 임베딩이 필요합니다.

### 2.1 임베딩이란 무엇인가

임베딩(Embedding)은 텍스트를 고차원 벡터 공간의 한 점으로 변환하는 것입니다. 의미가 유사한 텍스트는 이 벡터 공간에서 가깝게 위치하고, 의미가 다른 텍스트는 멀리 위치합니다.

```
[임베딩 벡터 공간에서의 의미적 근접성]

"비 오는 날 실내 카페" ──┐
"우천 시 실내 공간"   ────┼──▶ 벡터 공간에서 가까운 위치 (높은 유사도)
"날씨 나쁠 때 카페"   ──┘

"폭포 야외 트레킹"    ──┐
"등산 외부 활동"      ────┼──▶ 벡터 공간에서 가까운 위치 (높은 유사도)
"아웃도어 하이킹"     ──┘

위 두 그룹 사이의 거리는 멀다 (낮은 유사도)
```

`text-embedding-3-small` 모델은 입력 텍스트를 1,536개의 실수값으로 구성된 벡터로 변환합니다. 이 1,536차원의 좌표가 텍스트의 "의미적 위치"를 나타냅니다.

### 2.2 임베딩 모델 선택 — text-embedding-3-small vs 대안들

임베딩 모델을 선택할 때 다음 세 가지 옵션을 검토했습니다:

| 모델 | 차원 | API 비용 (1M 토큰당) | 한국어 성능 | 결론 |
|------|------|----------------------|-------------|------|
| `text-embedding-ada-002` | 1,536 | $0.10 | 보통 | 구형, 대체 권장 |
| `text-embedding-3-small` | 1,536 | $0.02 | 우수 | **선택** |
| `text-embedding-3-large` | 3,072 | $0.13 | 최우수 | 비용 대비 효과 낮음 |
| Sentence-BERT (로컬) | 768 | 0 (자체 호스팅) | 낮음 | 인프라 복잡도 증가 |

`text-embedding-3-small`은 이전 세대인 `ada-002`보다 5배 저렴하면서 MTEB(Massive Text Embedding Benchmark) 기준으로 더 높은 성능을 보입니다. `text-embedding-3-large`는 품질은 더 높지만, LALA의 블로그 리뷰 수준의 텍스트에서 그 차이가 체감되기 어렵고 비용이 6.5배 높습니다. Sentence-BERT는 무료이지만 한국어 지원이 미흡하고, 자체 호스팅을 위한 GPU 인프라가 필요해 복잡도가 증가합니다.

### 2.3 임베딩 생성 파이프라인

```python
# src/collectors/process_attractions.py

from openai import AzureOpenAI

def generate_embeddings(text: str) -> list[float] | None:
    """단일 텍스트의 임베딩 벡터 생성 (1536차원)"""
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_VERSION
    )
    
    try:
        response = client.embeddings.create(
            input=text,
            model="text-embedding-3-small"  # Azure OpenAI 배포명
        )
        return response.data[0].embedding  # list[float], len=1536
    except Exception as e:
        logging.error(f"임베딩 생성 실패: {e}")
        return None


# src/collectors/load_review_pipeline.py

def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """여러 텍스트의 임베딩을 단일 API 호출로 일괄 생성 (비용 최적화)"""
    embedding_client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=EMBEDDING_API_VERSION
    )
    
    logging.info(f"🔢 {len(texts)}개 텍스트 임베딩 생성 중...")
    
    try:
        response = embedding_client.embeddings.create(
            model=EMBEDDING_DEPLOYMENT_NAME,  # "text-embedding-3-small"
            input=texts  # 리스트로 전달 → 단 1번의 API 호출
        )
        
        # response.data는 input과 동일한 순서로 정렬됨 (순서 보장)
        embeddings = [item.embedding for item in response.data]
        logging.info(f"✅ 임베딩 생성 완료: {len(embeddings)}개")
        return embeddings
        
    except Exception as e:
        logging.error(f"배치 임베딩 오류: {e}")
        return []
```

**임베딩 대상 텍스트 설계** — 무엇을 임베딩할 것인가는 RAG 품질에 직결됩니다. 우리는 리뷰 원문을 그대로 임베딩하는 대신, LLM이 추출한 의미 있는 정보를 조합하여 임베딩합니다:

```python
# 임베딩 대상 텍스트 구성 (단순 원문보다 풍부한 시맨틱)
combined_text = (
    f"{attraction_name}. "                    # 장소명
    f"{analysis['summary_ko']}. "             # LLM 3줄 요약
    f"{' '.join(analysis['atmosphere_ko'])}. " # 분위기 키워드 배열
    f"{analysis['tips_ko']}"                  # 방문 팁
)
# 예: "수원 화성. 조선시대 성곽으로 유네스코 세계문화유산에..."
#     "고즈넉한 역사적인 사진찍기좋은."
#     "주차는 방문자센터 이용 권장. 야경도 아름다워 저녁 방문 추천."
```

---

## 3. pgvector — PostgreSQL 안에 벡터 DB를 담다

### 3.1 왜 전용 벡터 DB를 선택하지 않았는가

2024년 기준으로 벡터 데이터베이스 시장에는 다양한 옵션이 있습니다. 우리는 pgvector를 선택하기 전에 다음 옵션들을 검토했습니다.

**Pinecone**
- 장점: 완전 관리형(Managed), 수십억 벡터 규모의 높은 성능
- 단점: 별도 서비스로 관계형 메타데이터와의 조인 불가 → 애플리케이션 레이어에서 두 번 쿼리
- 단점: 무료 티어 제한, 프로덕션 플랜 월 수십~수백 달러

**Weaviate**
- 장점: GraphQL 인터페이스, 하이브리드 검색 내장
- 단점: 자체 호스팅 시 운영 부담, 관리형은 비용 높음
- 단점: 팀이 새로운 쿼리 언어(WQL)와 데이터 모델을 학습해야 함

**Azure AI Search (구 Azure Cognitive Search)**
- 장점: Azure 생태계 통합, 하이브리드 검색
- 단점: 인덱스당 과금 모델, 소규모 데이터에는 과도한 비용
- 단점: PostgreSQL 데이터와의 조인을 위해 데이터 복제 필요

**pgvector (선택)**
- 장점: 이미 사용 중인 PostgreSQL에 `CREATE EXTENSION IF NOT EXISTS vector;` 한 줄로 활성화
- 장점: 벡터와 관계형 데이터를 단일 쿼리에서 JOIN 가능
- 장점: pgvector 전용 인프라 비용 없음
- 단점: 수억 건 이상의 초대규모 벡터에서는 전문 벡터 DB보다 성능 낮을 수 있음
- 단점: ANN(Approximate Nearest Neighbor) 인덱스 튜닝 필요 (IVFFlat, HNSW)

**결정의 핵심**은 "규모의 경제"입니다. LALA가 처리하는 벡터 수는 수십만 개 수준으로, 전문 벡터 DB가 필요한 수억~수십억 건과는 거리가 멉니다. 이 규모에서는 pgvector가 충분한 성능을 제공하면서, **관계형 데이터와의 자연스러운 조인**이라는 압도적인 이점을 제공합니다.

### 3.2 pgvector 스키마 설계

```sql
-- sql/ddl/attaction_reviews.sql

-- 확장 기능 활성화
CREATE EXTENSION IF NOT EXISTS postgis;   -- 공간 데이터
CREATE EXTENSION IF NOT EXISTS vector;   -- 벡터 데이터

-- 관광지 리뷰 테이블 (pgvector 임베딩 포함)
CREATE TABLE locallink.attraction_reviews (
    id SERIAL PRIMARY KEY,
    attraction_name TEXT NOT NULL
        REFERENCES locallink.gyeonggi_attractions(attraction_name)
        ON DELETE CASCADE,
    title TEXT,
    description TEXT,
    post_date DATE,
    clean_text TEXT,                        -- HTML 제거 + 광고 필터링된 텍스트
    extracted_keywords TEXT,               -- LLM 추출 키워드 (JSON 문자열)
    embedding VECTOR(1536),                -- pgvector: text-embedding-3-small 벡터
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 성능을 위한 인덱스
-- 1. 관광지명 + 날짜 기준 정렬 인덱스 (최신 리뷰 우선)
CREATE INDEX idx_attraction_reviews_name_date
    ON locallink.attraction_reviews (attraction_name, created_at DESC);

-- 2. pgvector HNSW 인덱스 (Approximate Nearest Neighbor 검색)
--    IVFFlat보다 검색 속도 빠름, 빌드 시간과 메모리 사용량 높지만
--    백만 건 미만에서는 HNSW가 일반적으로 더 권장됨
CREATE INDEX idx_attraction_reviews_embedding_hnsw
    ON locallink.attraction_reviews
    USING hnsw (embedding vector_cosine_ops)  -- 코사인 거리 연산자 사용
    WITH (m = 16, ef_construction = 64);      -- HNSW 파라미터 튜닝

-- 식당 리뷰 테이블 (구조 동일)
CREATE TABLE locallink.restaurant_reviews (
    id SERIAL PRIMARY KEY,
    restaurant_name TEXT NOT NULL,
    title TEXT,
    description TEXT,
    clean_text TEXT,
    extracted_keywords TEXT,
    embedding VECTOR(1536),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- LLM 합성 도슨트 정보 테이블 (임베딩 캐시)
CREATE TABLE locallink.attraction_details (
    attraction_name TEXT PRIMARY KEY
        REFERENCES locallink.gyeonggi_attractions(attraction_name),
    summary_ko TEXT,       -- LLM 한국어 3줄 요약
    summary_en TEXT,       -- LLM 영어 3줄 요약
    atmosphere_ko TEXT,    -- 분위기 키워드 배열 (JSON:  ["고즈넉한", "역사적인"])
    atmosphere_en TEXT,
    tips_ko TEXT,          -- 방문 실용 팁 (한국어)
    tips_en TEXT,          -- 방문 실용 팁 (영어)
    embedding VECTOR(1536), -- 요약+키워드+팁의 통합 임베딩
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**HNSW vs IVFFlat 인덱스 선택** — pgvector는 두 가지 ANN 인덱스를 지원합니다:

```
[IVFFlat]
- Inverted File Index + Flat storage
- 벡터를 클러스터로 나누어 클러스터 내에서만 탐색
- 장점: 빌드 속도 빠름, 메모리 효율적
- 단점: 클러스터 경계 근처 벡터의 recall 저하 가능
- 적합: 수백만 건 이상의 대규모 데이터셋

[HNSW]  ← LALA 채택
- Hierarchical Navigable Small World graph
- 계층적 그래프 구조로 탐색 경로 단축
- 장점: 높은 recall, 빠른 검색 속도
- 단점: 빌드 시간 길고 메모리 사용량 많음
- 적합: 수십만~수백만 건 수준, 검색 품질 우선

LALA는 수십만 건 규모 + 도슨트 품질이 서비스 핵심
→ HNSW 선택
```

### 3.3 벡터 유사도 검색 연산자

pgvector는 세 가지 거리 연산자를 제공합니다:

```sql
-- 1. 코사인 거리 (<=>): 방향 유사성 측정, 크기(magnitude) 무관
--    텍스트 임베딩에 가장 널리 사용
SELECT clean_text, embedding <=> $1::vector AS cosine_distance
FROM locallink.attraction_reviews
ORDER BY cosine_distance ASC  -- 낮을수록 유사
LIMIT 5;

-- 2. L2 유클리디안 거리 (<->): 벡터 공간에서의 직선 거리
SELECT clean_text, embedding <-> $1::vector AS l2_distance
FROM locallink.attraction_reviews
ORDER BY l2_distance ASC
LIMIT 5;

-- 3. 내적/부호 반전 (<#>): 최대 내적(maximum inner product)
SELECT clean_text, embedding <#> $1::vector AS neg_inner_product
FROM locallink.attraction_reviews
ORDER BY neg_inner_product ASC  -- 가장 높은 내적이 가장 유사
LIMIT 5;
```

LALA는 **코사인 유사도(`<=>`)**를 사용합니다. 텍스트 임베딩의 경우, 리뷰의 길이(벡터 크기)보다 내용(벡터 방향)이 유사도 판단에 더 중요하기 때문입니다. 짧은 리뷰 "예쁘고 맛있어요"와 긴 리뷰 "정말 예쁘고 분위기 좋고 음식도 다 맛있어서 계속 오고 싶어요" 사이의 의미적 유사성은 코사인 유사도가 더 잘 포착합니다.

---

## 4. 전체 RAG 추론 파이프라인 — 질문에서 도슨트까지

이제 모든 퍼즐 조각이 갖춰졌습니다. 사용자가 iOS 앱에서 도슨트를 요청할 때부터 GPT-4o-mini가 응답을 생성하기까지의 전체 흐름을 단계별로 추적합니다.

### 4.1 전체 흐름 다이어그램

```
[RAG 추론 파이프라인 전체 흐름]

iOS 앱
  │ POST /api/ios/v1/docent/script
  │ Body: {place_id: "123", category: "attraction", language: "ko", mode: "brief"}
  ▼
Flask API (Docker Container, Azure App Service)
  │
  ├─ 1단계: 요청 파라미터 검증
  │    category ∈ {"attraction", "restaurant", "event"}
  │    language ∈ {"ko", "en"}
  │    mode ∈ {"brief", "detail"}
  │
  ├─ 2단계: 캐시 확인 (7일 TTL)
  │    SELECT script FROM docent_script_cache
  │    WHERE place_id=$1 AND category=$2 AND language=$3 AND mode=$4
  │    AND created_at > NOW() - INTERVAL '7 days'
  │    → 캐시 히트 시 즉시 반환 (source="cache")
  │
  ├─ 3단계: 컨텍스트 로드 (캐시 미스 시)
  │    A. 장소 기본 정보 (attraction_name, address, region)
  │    B. LLM 요약 (summary_ko, atmosphere_ko, tips_ko)
  │    C. 현재 날씨 (is_rain_snow, temperature, pm10)
  │    D. 관련 리뷰 (pgvector 코사인 유사도 Top-5)
  │         → place_name 임베딩으로 가장 관련성 높은 리뷰 검색
  │
  ├─ 4단계: LLM 추론 (Azure OpenAI GPT-4o-mini)
  │    System Prompt: 도슨트 역할 + 가이드라인
  │    User Message: 컨텍스트(리뷰+날씨+장소정보) + 요청 파라미터
  │    → 도슨트 스크립트 생성 (ko/brief: 3~4문장)
  │
  ├─ 5단계: 결과 캐싱
  │    INSERT INTO docent_script_cache (TTL 7일)
  │
  └─ 6단계: 응답 반환
       {script: "...", source: "llm", generated_at: "...", ttl_sec: 604800}

iOS 앱 (선택적)
  │ POST /api/ios/v1/docent/audio
  │ Body: {script: "...", language: "ko"}
  ▼
Azure Cognitive Services (TTS)
  │ 음성 합성: ko-KR-SunHiNeural (한국어)
  │            en-US-JennyNeural (영어)
  │            ja-JP-NanamiNeural (일본어)
  └─▶ MP3 바이너리 스트림 반환
```

### 4.2 Flask API 엔드포인트 구현

```python
# src/frontend/web/routes/ios_api.py

@ios_bp.route("/v1/docent/script", methods=["POST"])
def create_docent_script():
    """AI 도슨트 스크립트 생성 엔드포인트"""
    
    payload = request.get_json(silent=True) or {}
    
    # 입력 파라미터 파싱 및 기본값 처리
    place_id = str(payload.get("place_id") or "").strip()
    category = str(payload.get("category") or "").strip().lower()
    language = str(payload.get("language") or "ko").strip().lower()
    mode = str(payload.get("mode") or "brief").strip().lower()
    
    # 입력값 검증 (화이트리스트 방식 — 예상치 못한 값 차단)
    if category not in {"attraction", "restaurant", "event"}:
        return jsonify({"error": "category must be attraction|restaurant|event"}), 400
    if language not in {"ko", "en"}:
        return jsonify({"error": "language must be ko|en"}), 400
    if mode not in {"brief", "detail"}:
        return jsonify({"error": "mode must be brief|detail"}), 400
    if not place_id:
        return jsonify({"error": "place_id is required"}), 400
    
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                result = generate_docent_script(
                    cursor=cursor,
                    place_id=place_id,
                    category=category,
                    language=language,
                    mode=mode,
                )
            conn.commit()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logging.exception("도슨트 스크립트 생성 오류")
        return jsonify({"error": str(exc)}), 500
    
    return jsonify({
        "place_id": result.place_id,
        "category": result.category,
        "language": result.language,
        "mode": result.mode,
        "script": result.script,
        "source": result.source,      # "llm" | "fallback" | "cache"
        "generated_at": result.generated_at,
        "ttl_sec": result.ttl_sec,
    }), 200
```

### 4.3 7일 TTL 캐싱 전략

도슨트 스크립트 생성은 LLM API 호출이 포함되어 있어 비용과 레이턴시가 발생합니다. 같은 장소에 대한 도슨트 요청이 반복될 때마다 매번 LLM을 호출하는 것은 비효율적입니다. 장소의 특성(분위기, 역사, 팁)은 매일 바뀌지 않으므로, 7일 TTL 캐싱 전략을 도입했습니다:

```python
# src/frontend/web/services/docent_service.py

@dataclass
class DocentScriptResult:
    place_id: str
    category: str
    language: str
    mode: str
    script: str
    source: str   # "llm" | "fallback" | "cache"
    generated_at: str
    ttl_sec: int = 604800  # 7일 = 7 * 24 * 3600

def generate_docent_script(
    cursor,
    place_id: str,
    category: str,
    language: str,
    mode: str
) -> DocentScriptResult:
    """RAG + LLM 도슨트 스크립트 생성 (캐시 포함)"""
    
    # 1단계: 캐시 확인
    cached = _load_cached_script(cursor, place_id, category, language, mode)
    if cached is not None:
        return cached  # 7일 내 캐시 히트

    # 2단계: DB에서 컨텍스트 로드
    context = _load_context(cursor, place_id, category)
    
    # 3단계: LLM 호출 (최대 2회 재시도)
    script = ""
    source = "fallback"
    llm_error = None
    
    max_attempts = min(_int_env("DOCENT_LLM_MAX_ATTEMPTS", 1), 2)
    
    for attempt in range(max_attempts):
        try:
            script = _generate_with_llm(
                context=context,
                category=category,
                language=language,
                mode=mode
            )
            source = "llm"
            llm_error = None
            break  # 성공 시 루프 종료
        except Exception as exc:
            llm_error = exc
            logging.warning(f"LLM 시도 {attempt+1}/{max_attempts} 실패: {exc}")
    
    # 4단계: LLM 실패 시 Fallback 스크립트
    if source != "llm":
        if llm_error:
            logging.error(f"LLM 최종 실패: place_id={place_id}, error={llm_error}")
        script = _fallback_script(context=context, category=category, language=language, mode=mode)
    
    # 5단계: 캐시 저장
    _store_cache(cursor, place_id=place_id, category=category,
                 language=language, mode=mode, script=script, source=source)
    
    return DocentScriptResult(
        place_id=place_id,
        category=category,
        language=language,
        mode=mode,
        script=script,
        source=source,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _load_cached_script(cursor, place_id, category, language, mode):
    """7일 TTL 캐시 조회"""
    cursor.execute("""
        SELECT script, source, generated_at
        FROM locallink.docent_script_cache
        WHERE place_id = %s
          AND category = %s
          AND language = %s
          AND mode = %s
          AND generated_at > NOW() - INTERVAL '7 days'
        ORDER BY generated_at DESC
        LIMIT 1
    """, (place_id, category, language, mode))
    
    row = cursor.fetchone()
    if row:
        return DocentScriptResult(
            place_id=place_id, category=category,
            language=language, mode=mode,
            script=row['script'], source="cache",
            generated_at=row['generated_at'].isoformat()
        )
    return None
```

### 4.4 LLM 추론 — 프롬프트 엔지니어링의 핵심

LLM에게 무엇을, 어떻게 요청하느냐에 따라 도슨트 스크립트의 품질이 결정됩니다. 우리는 수십 번의 프롬프트 이터레이션을 거쳐 최적의 시스템 프롬프트를 정제했습니다.

```python
# src/frontend/web/services/docent_service.py

def _generate_with_llm(context: dict, category: str, language: str, mode: str) -> str:
    """Azure OpenAI GPT-4o-mini를 사용한 도슨트 스크립트 생성"""
    
    # Azure OpenAI 클라이언트 초기화 (Key Vault에서 자격증명 로드)
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
        max_retries=0,       # 자체 재시도 로직 사용
        timeout=llm_timeout  # 환경변수로 설정 가능 (기본 6초)
    )
    
    language_name = "Korean" if language == "ko" else "English"
    sentence_rule = "3~4" if mode == "brief" else "6~8"
    
    # 컨텍스트에서 스토리용 리뷰 선별 (최대 8개)
    facts = context.get("facts") or []
    if category == "attraction":
        facts = pick_story_reviews(facts, max_items=8)  # 감성적 리뷰 우선 선별
    facts_text = "\n".join(f"- {item}" for item in facts[:8])
    
    # 시스템 프롬프트: 캐릭터 + 가이드라인
    system_message = f"""You are 'LALA', a vibrant and witty AI docent for visitors exploring {context.get('region', 'Gyeonggi-do')} Korea.
[Mission] Create a natural, engaging audio guide script that brings this place to life.
[Guidelines]
1. Open with a warm greeting that sets the mood for {context.get('name', 'this place')}.
2. Weave in 2-3 specific details from real visitor reviews — make them feel authentic.
3. If weather context is provided, naturally reference it (e.g., a rainy day → mention cozy indoor atmosphere).
4. Use conversational, rhythmic phrasing suitable for listening through earphones.
5. Do NOT fabricate facts not present in the provided data.
6. Length: {sentence_rule} sentences. End with a gentle invitation to explore.
7. Language: Write entirely in {language_name}.

[Current Context]
- Name: {context.get('name')}
- Region: {context.get('region')}
- Address: {context.get('address')}
- Atmosphere: {context.get('atmosphere', '')}
- Visitor Tips: {context.get('tips', '')}
- Weather: {context.get('weather_summary', 'No weather data available')}
"""
    
    # 사용자 메시지: 실제 리뷰 데이터
    user_message = f"""Generate a docent script for: {context.get('name')}

[Real visitor reviews (use these as inspiration, not quotes)]:
{facts_text}

Create an engaging {mode} script for audio playback."""
    
    response = client.chat.completions.create(
        model=deployment,
        temperature=0.5,       # 창의성과 일관성의 균형점
        max_tokens=320,        # brief: ~1분 분량
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
    )
    
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("LLM이 빈 응답을 반환했습니다")
    
    return content
```

**프롬프트 설계 원칙 — 왜 이 구조인가**

1. **"Do NOT fabricate facts"** 지시어: LLM의 환각(Hallucination)을 방지하는 가장 중요한 지시어입니다. 제공된 컨텍스트에 없는 정보를 만들어내지 않도록 명시적으로 제한합니다.

2. **temperature=0.5**: 도슨트 스크립트는 창의적이되 사실 기반이어야 합니다. temperature=0에 가까울수록 결정론적이고 반복적인 텍스트가 생성되며, 1에 가까울수록 창의적이지만 사실과 멀어질 수 있습니다. 0.5는 두 특성의 균형점입니다.

3. **max_tokens=320**: 텍스트-음성 변환(TTS) 기준으로 1분 분량의 스크립트에 해당합니다. 너무 긴 스크립트는 사용자 집중도를 떨어뜨립니다.

4. **리뷰를 "인용"이 아닌 "영감의 원천"으로**: "사용자 A가 이렇게 말했다"처럼 직접 인용하면 부자연스럽습니다. 대신 리뷰의 핵심 감성과 정보를 AI 도슨트의 목소리로 재해석하도록 "use as inspiration, not quotes"로 지시합니다.

### 4.5 키워드 추출 프롬프트 — 구조화된 JSON 출력

도슨트 스크립트 생성 외에도, LLM은 리뷰에서 키워드를 추출하는 역할을 합니다. 이때는 자유형식 텍스트가 아닌 **정확한 JSON 구조**가 필요합니다:

```python
# tests/llm_review_processor_test.py (검증된 시스템 프롬프트)

KEYWORD_EXTRACTION_SYSTEM_PROMPT = """
당신은 외국인 관광객을 위한 한국 로컬 명소 추천 AI 데이터 분석가입니다.
사용자가 제공하는 블로그 리뷰 텍스트들을 종합적으로 분석하여,
해당 장소의 분위기와 특징을 가장 잘 나타내는 핵심 키워드를 추출해야 합니다.

[작업 지시 사항]
1. 리뷰 텍스트의 전체적인 문맥을 파악하십시오.
2. "협찬", "소정의 원고료", "제공받아" 등 광고성 멘트는 완전히 무시하십시오.
3. 외국인 관광객이 이 장소를 선택할 때 매력적으로 느낄 만한
   '형용사' 3개와 '명사' 3개를 추출하십시오.
4. 출력은 반드시 아래의 JSON 포맷으로만 응답하세요. 다른 텍스트 없이.

[출력 JSON 포맷]
{
  "adjectives": ["고즈넉한", "활기찬", "사진찍기좋은"],
  "nouns": ["야경", "전통건축", "산책로"]
}
"""

response = client.chat.completions.create(
    model=DEPLOYMENT_NAME,
    messages=[
        {"role": "system", "content": KEYWORD_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": f"장소: {attraction_name}\n리뷰:\n{combined_reviews}"}
    ],
    response_format={"type": "json_object"},  # JSON 모드 강제 (구조 보장)
    temperature=0.2,  # 낮은 temperature: 일관된 JSON 출력
    max_tokens=150    # 짧은 응답으로 비용 최소화
)
```

`response_format={"type": "json_object"}`는 OpenAI의 JSON Mode입니다. 이를 사용하면 모델이 반드시 유효한 JSON을 출력하도록 강제됩니다. 마크다운 코드 블록이나 설명 텍스트로 감싸진 JSON 문자열로 파싱 실패가 발생하는 문제를 완전히 해결합니다.

---

## 5. 실제 RAG 쿼리 — 모든 것의 통합

이제 앞서 설명한 PostGIS, pgvector, 날씨 플래그가 실제 RAG 컨텍스트 구성 쿼리에서 어떻게 결합되는지 보겠습니다:

```python
# src/frontend/web/services/docent_service.py

def _load_context(cursor, place_id: str, category: str) -> dict:
    """RAG 추론을 위한 전체 컨텍스트 로드"""
    
    if category == "attraction":
        # 1. 장소 기본 정보 + LLM 요약 + 날씨 통합 쿼리
        cursor.execute("""
            SELECT
                a.attraction_name AS name,
                a.road_address AS address,
                a.city_county_name AS region,
                ad.summary_ko,
                ad.atmosphere_ko,
                ad.tips_ko,
                -- 현재 날씨 (LATERAL JOIN)
                w.temperature,
                w.is_rain_snow,
                w.is_bad_dust,
                w.is_heatwave,
                w.pm10
            FROM locallink.gyeonggi_attractions a
            LEFT JOIN locallink.attraction_details ad
                ON a.attraction_name = ad.attraction_name
            LEFT JOIN LATERAL (
                SELECT temperature, is_rain_snow, is_bad_dust, is_heatwave, pm10
                FROM locallink.realtime_weather_conditions
                WHERE location = a.city_county_name
                ORDER BY record_time DESC
                LIMIT 1
            ) w ON TRUE
            WHERE a.id = %s
        """, (place_id,))
        basic_ctx = cursor.fetchone()
        
        if not basic_ctx:
            raise ValueError(f"장소를 찾을 수 없습니다: place_id={place_id}")
        
        # 날씨 요약 텍스트 구성
        weather_parts = []
        if basic_ctx['is_rain_snow']:
            weather_parts.append("현재 강수 중 (비 또는 눈)")
        if basic_ctx['is_bad_dust']:
            weather_parts.append(f"미세먼지 나쁨 (PM10: {basic_ctx['pm10']}µg/m³)")
        if basic_ctx['is_heatwave']:
            weather_parts.append(f"폭염 주의 (기온: {basic_ctx['temperature']}°C)")
        weather_summary = ", ".join(weather_parts) if weather_parts else "날씨 양호"
        
        # 2. pgvector로 관련 리뷰 검색 (장소명을 쿼리로 사용)
        place_name_embedding = generate_embeddings(basic_ctx['name'])
        
        if place_name_embedding:
            cursor.execute("""
                SELECT clean_text
                FROM locallink.attraction_reviews
                WHERE attraction_name = %s
                  AND clean_text IS NOT NULL
                  AND LENGTH(clean_text) > 30  -- 너무 짧은 리뷰 제외
                ORDER BY embedding <=> %s::vector  -- 코사인 유사도 순
                LIMIT 8
            """, (basic_ctx['name'], place_name_embedding))
            reviews = [row['clean_text'] for row in cursor.fetchall()]
        else:
            # 임베딩 생성 실패 시 최신 리뷰 폴백
            cursor.execute("""
                SELECT clean_text FROM locallink.attraction_reviews
                WHERE attraction_name = %s AND clean_text IS NOT NULL
                ORDER BY created_at DESC LIMIT 8
            """, (basic_ctx['name'],))
            reviews = [row['clean_text'] for row in cursor.fetchall()]
        
        return {
            "name": basic_ctx['name'],
            "address": basic_ctx['address'],
            "region": basic_ctx['region'],
            "summary": basic_ctx['summary_ko'] or "",
            "atmosphere": basic_ctx['atmosphere_ko'] or "",
            "tips": basic_ctx['tips_ko'] or "",
            "weather_summary": weather_summary,
            "facts": reviews,  # LLM에게 전달될 실제 리뷰 텍스트
        }
```

---

## 6. 음성 합성 — 도슨트가 입을 열다

텍스트로 생성된 도슨트 스크립트는 Azure Cognitive Services의 TTS(Text-to-Speech)를 통해 MP3 음성으로 변환됩니다:

```python
# src/services/speech_synthesizer.py

def synthesize_speech_mp3(script: str, language: str = "ko") -> bytes:
    """도슨트 스크립트를 MP3 오디오로 변환"""
    
    # 언어별 음성 선택
    voice_map = {
        "ko": "ko-KR-SunHiNeural",   # 한국어: 밝은 여성 목소리
        "en": "en-US-JennyNeural",   # 영어: 친근한 여성 목소리
        "ja": "ja-JP-NanamiNeural",  # 일본어: 자연스러운 여성 목소리
    }
    voice_name = voice_map.get(language, "ko-KR-SunHiNeural")
    
    # SSML(Speech Synthesis Markup Language) 생성
    # html.escape()로 특수문자 처리 (보안 + 인코딩 오류 방지)
    safe_script = html.escape(script)
    
    ssml_text = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{language}-KR'>
    <voice name='{voice_name}'>
        <prosody rate='0%' pitch='0%'>
            {safe_script}
        </prosody>
    </voice>
</speak>"""
    
    # Azure Speech 엔드포인트 호출
    endpoint = f"https://{SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",  # MP3 16kHz
        "User-Agent": "LALA-AI-Docent/1.0"
    }
    
    response = requests.post(endpoint, headers=headers, data=ssml_text.encode("utf-8"))
    
    if response.status_code != 200:
        raise SpeechSynthesisError(
            f"TTS 합성 실패: status={response.status_code}",
            status_code=502
        )
    
    return response.content  # MP3 바이너리
```

---

## 7. 성능 최적화 — 프로덕션에서의 레이턴시 관리

RAG 파이프라인은 여러 단계로 구성되어 있어 각 단계의 레이턴시가 누적됩니다:

```
[레이턴시 분석]

1. 캐시 확인:           ~5ms   (PostgreSQL 단순 SELECT)
2. 컨텍스트 로드:        ~20ms  (JOIN 쿼리 + 날씨 LATERAL JOIN)
3. 쿼리 임베딩 생성:     ~200ms (Azure OpenAI API 호출)
4. pgvector 검색:        ~10ms  (HNSW 인덱스 ANN 검색)
5. LLM 추론:            ~2000ms (GPT-4o-mini API 호출)
6. 캐시 저장:           ~10ms  (PostgreSQL INSERT)
──────────────────────────────────
총 (캐시 미스 시):       ~2245ms (약 2.2초)
총 (캐시 히트 시):       ~5ms   (거의 즉각적)
```

7일 TTL 캐싱 덕분에 반복 요청의 체감 성능은 매우 빠릅니다. 캐시 미스가 발생하는 경우(새로운 장소 첫 요청 또는 7일 만료 후)에만 2~3초의 지연이 발생합니다. 이 경우 iOS 앱은 로딩 인디케이터를 표시하여 사용자 경험을 보호합니다.

---

## 마치며

이번 편에서는 PostGIS, text-embedding-3-small, pgvector, GPT-4o-mini가 하나의 RAG 파이프라인으로 통합되는 과정을 상세히 살펴보았습니다. 핵심 메시지를 다시 한번 정리하면:

- **PostGIS**: "어디"라는 공간적 맥락을 WGS84 기반 정확한 거리 계산으로 처리
- **text-embedding-3-small**: 텍스트의 "의미"를 1,536차원 벡터로 변환
- **pgvector + HNSW 인덱스**: PostgreSQL 안에서 고성능 의미 검색 가능
- **GPT-4o-mini**: 검색된 컨텍스트를 바탕으로 살아있는 도슨트 스크립트 생성
- **7일 TTL 캐시**: 반복 요청에서 LLM 비용 없이 즉각 응답

다음 편에서는 이 파이프라인을 구축하면서 실제로 마주쳤던 **가장 까다로운 트러블슈팅**을 다룹니다. 공공 API의 불완전한 데이터가 어떻게 파이프라인 전체를 멈추게 했고, 우리가 그것을 어떻게 해결했는지 P-C-S 프레임워크로 낱낱이 해부합니다.

---

> **이전 편**: [2부 — 데이터 파이프라인: 배치와 실시간의 조화](./02_Data_Pipeline_Batch_and_Realtime.md)  
> **다음 편**: [4부 — 트러블슈팅: 데이터 브로커와 자료형 불일치](./04_Troubleshooting_PCS_Framework.md)
