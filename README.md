# 🌏 LALA: Local Area, Local Answer
> **"Your Korean Buddy, 서울 너머 진짜 한국의 숨결을 잇다"**

**LALA**는 정보의 갈라파고스화로 인해 서울에만 편중된 외국인 관광객의 발걸음을 내국인의 실시간 일상 데이터(카드 소비, 지역 커뮤니티)를 활용해 전국의 로컬 명소로 안내하는 **지능형 로컬 관광 가이드 솔루션**입니다.

---

## 🎬 시연 영상 (Demo)

> GitHub README 보안 정책상 YouTube `iframe` 직접 임베드는 지원되지 않습니다.  
> 아래 썸네일을 클릭하면 영상이 바로 재생됩니다.

[![LALA Demo Video](https://img.youtube.com/vi/b2GsLqoKbqY/hqdefault.jpg)](https://youtube.com/shorts/b2GsLqoKbqY?feature=share)

---

## 🚀 주요 기능 (Key Features)

### 1. 데이터 기반 로컬 랭킹 시스템 (Data-Driven Ranking)
- **내국인 찐 맛집 추천:** 5억 건의 경기도 카드 소비 데이터와 당근마켓 지역 커뮤니티 언급 데이터를 결합하여 광고가 아닌 실제 현지인이 찾는 명소를 발굴합니다.
- **공정한 데이터 정규화:** 특정 대형 상권 쏠림을 방지하기 위해 **IQR 이상치 보정** 및 **Min-Max 정규화**를 적용하여 공정한 추천 알고리즘을 구현했습니다.

### 2. AI 도슨트 및 음성 인터페이스 (AI Docent & TTS)
- **맞춤형 가이드:** 네이버 리뷰 데이터를 Azure OpenAI로 분석하여 역사, 유래, 전설 등 스토리텔링이 담긴 다국어 가이드를 제공합니다.
- **멀티모달 경험:** Azure Speech(TTS)를 통해 시각 정보뿐만 아니라 음성으로도 명소 설명을 들을 수 있는 배리어 프리 기능을 지원합니다.

### 3. 기상 인지 지능형 엔진 (Weather-Aware Engine)
- **선제적 코스 전환:** 실시간 기상 상태(강수, 미세먼지, 한파/폭염)를 감지하여, 악천후 시 야외 코스를 즉시 실내 명소나 카페로 대체 제안하는 **단계적 폴백(Fallback) 알고리즘**을 탑재했습니다.

### 4. 고도화된 모바일 경험 (iOS Optimization)
- **스마트 클러스터링:** 뷰포트 기반 필터링과 줌 레벨별 캐시 키를 도입하여 대량의 마커 렌더링 성능을 최적화하고 사용자 중심의 지도 UI를 제공합니다.
- **데이터 주도 UX:** AI 시선 예측(Attention Insight) 모델을 통해 인터페이스의 시각적 위계를 과학적으로 교정했습니다.

---

## 🛠 기술 스택 (Tech Stack)

### Infrastructure & DevOps
- **Cloud:** Azure (Functions, OpenAI, Key Vault, Event Hub, Stream Analytics)
- **Security:** **Secret-Zero** 환경 (GitHub Actions OIDC + Azure Key Vault + Managed Identity)
- **Workflow:** Modern Python Workflow (pyproject.toml 기반 패키지화 및 싱글톤 KeyVaultManager)

### Data & Backend
- **Database:** PostgreSQL (PostGIS를 이용한 반경 기반 공간 검색, pgvector를 이용한 AI 유사도 검색)
- **Pipeline:** Azure Queue 기반 분산 크롤링 처리 및 데이터 파이프라인 자동화 (Crawl → Aggregator)
- **Monitoring:** Power BI 하이브리드 대시보드 (실시간 장애 지표 + 배치형 비용 관제)

### Frontend
- **Mobile:** Swift (iOS), GPS 기반 실시간 능동형 UI
- **Web:** Flask (계획 단계 서비스 제공)

---

## 🔍 트러블슈팅 및 성능 최적화 (Troubleshooting)

- **데이터 파이프라인 안정화:** 공공 데이터 API의 불규칙한 데이터 유입("점검중" 등)에 대응하기 위한 예외 처리 및 BIGINT 형변환 로직 구축.
- **지도 성능 개선:** 최대 확대 구간에서 강제 클러스터링을 비활성화하고 뷰포트 기반 마커 필터링을 적용해 렌더링 지연 해결.
- **AI 신뢰성 확보:** 식도락 리뷰가 명소 도슨트에 섞이는 환각 현상을 방지하기 위해 `clean_and_filter_text()` 가드레일 도입.

---

## ⚖ 인공지능 윤리 및 투명성 (Ethics & XAI)

- **XAI(설명 가능한 AI):** '왜 이 장소를 추천했는지'에 대한 근거와 기상 데이터 출처를 투명하게 공개합니다.
- **개인정보 보호:** 위치 정보 활용에 대한 명시적 동의 절차를 준수하며 시크릿 키 중앙 관리를 통해 데이터 보안을 강화했습니다.
