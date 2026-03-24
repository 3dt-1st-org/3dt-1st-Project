# LALA 프로젝트 5부: AI 윤리, 보안 아키텍처, 그리고 프로젝트 회고

> **시리즈**: Azure + PostgreSQL + pgvector로 RAG 기반 AI 도슨트 서비스 구축하기  
> **분류**: AI Ethics, Security, Key Vault, Microsoft Responsible AI, Retrospective  
> **작성일**: 2026년 3월 24일  

---

## 들어가며 — 기술은 가치 중립이지 않다

"AI를 만들었다"는 것은 단순히 코드를 작성했다는 뜻이 아닙니다. 그것은 어떤 정보를 어떤 방식으로 어떤 사람에게 전달할지를 결정하는 시스템을 만들었다는 뜻입니다. LALA는 경기도를 방문하는 외국인 관광객에게 AI가 생성한 도슨트 스크립트를 제공하는 서비스입니다. 10개의 언어로 수백만 명에게 도달할 수 있는 서비스에서 AI가 편향된 정보나 부정확한 내용을 생성한다면, 그 피해는 코드 한 줄의 버그와는 비교할 수 없습니다.

이 마지막 편에서는 LALA 프로젝트가 어떻게 **Microsoft Responsible AI 6대 원칙**을 실제 코드 수준에서 구현했는지, **Azure Key Vault와 Managed Identity**로 어떻게 "소스코드에 비밀이 없는" 아키텍처를 구현했는지, 그리고 다음 단계를 향한 회고를 기술합니다.

---

## 1부: Microsoft Responsible AI 6대 원칙과 LALA의 구현

Microsoft의 Responsible AI 프레임워크는 AI 시스템이 갖춰야 할 6가지 핵심 원칙을 정의합니다: **공정성(Fairness), 신뢰성(Reliability), 개인정보보호(Privacy), 포용성(Inclusiveness), 투명성(Transparency), 책임성(Accountability)**. LALA의 `AI_ETHICS_CLASSIFICATION.md`는 이 원칙들을 실제 코드의 어느 파일, 어느 함수에서 구현했는지 매핑합니다.

---

### 원칙 1: 투명성 (Transparency) — "이것은 AI가 만든 내용입니다"

AI 시스템의 투명성은 "사용자가 자신이 AI와 상호작용하고 있음을 알 권리"에 관한 것입니다. LALA에서는 도슨트 스크립트가 실시간 LLM 생성인지, 캐시된 이전 결과인지, 또는 장애 시 대체 텍스트인지를 API 응답에 명시합니다:

```python
# src/services/docent_service.py

from dataclasses import dataclass
from typing import Literal

@dataclass
class DocentScriptResult:
    """도슨트 스크립트 생성 결과
    
    source 필드는 사용자 인터페이스에 정보 출처를 표시하기 위한 투명성 메타데이터.
    - "llm": 이번 요청에 실시간으로 LLM이 생성한 스크립트
    - "cache": 7일 내 캐시된 LLM 생성 스크립트 (동일 품질)
    - "fallback": LLM 실패 시 미리 작성된 대체 텍스트 (품질 차이 있음)
    """
    attraction_name: str
    language: str
    script_text: str
    source: Literal["llm", "cache", "fallback"]
    cache_age_hours: float | None = None  # 캐시라면 몇 시간 전 생성인지
```

iOS 앱에서는 이 `source` 값을 받아 다음과 같이 표시합니다:

```swift
// iOS 앱 UI 레이어
switch docentScript.source {
case "llm":
    sourceLabel.text = NSLocalizedString("map_tour_source_llm", comment: "")
    // → "AI 생성" (한국어), "AI Generated" (영어)
case "cache":
    sourceLabel.text = NSLocalizedString("map_tour_source_cache", comment: "")
    // → "AI 생성 (캐시)" 
case "fallback":
    sourceLabel.text = NSLocalizedString("map_tour_source_fallback", comment: "")
    // → "기본 정보"
    fallbackNoticeView.isHidden = false  // 대체 텍스트 안내 배너 표시
}
```

또한 Power BI 대시보드에서는 각 데이터 지표 옆에 데이터 출처(기상청 API, 에어코리아 API, 카드 매출 데이터)를 명시하여 의사결정자가 데이터의 신뢰도를 스스로 평가할 수 있도록 했습니다.

**투명성이 왜 중요한가?**

GPT-4o-mini는 때로 "환각(Hallucination)" — 사실이 아닌 그럴듯한 내용 생성 — 을 일으킬 수 있습니다. 특히 역사적 사실이나 특정 장소의 정보를 생성할 때 오류가 발생할 가능성이 있습니다. 사용자가 "이것은 AI가 생성한 내용입니다"를 명확히 알고 있다면, 중요한 결정(예: 식당 예약, 관광지 방문 여부)을 내리기 전에 다른 정보원을 참고할 동기가 생깁니다. AI 생성 콘텐츠를 "공식 정보"인 것처럼 포장하는 것은 사용자를 기만하는 것입니다.

---

### 원칙 2: 공정성 (Fairness) — "모든 식당이 공정하게 경쟁한다"

공정성 원칙은 AI 시스템이 특정 개인이나 그룹에 대한 편향을 만들거나 강화해서는 안 된다는 것입니다. LALA의 랭킹 시스템에는 세 가지 형태의 공정성 메커니즘이 있습니다:

**공정성 메커니즘 1: 광고성 리뷰 필터링**

```python
# src/services/review_pipeline.py

# 광고성 키워드 목록 (지속적으로 업데이트)
AD_KEYWORDS = [
    "협찬", "소정의 원고료", "광고", "체험단",
    "리뷰어", "제공받았", "서포터즈", "공식"
]

def clean_and_filter_text(review_text: str) -> str | None:
    """광고성 리뷰 필터링 (공정성 보장)
    
    광고 리뷰는 실제 방문 경험이 아니라 보상을 받고 작성된 내용.
    이를 AI 분석에 포함하면 특정 업체가 인위적으로 긍정 평가를 받게 됨.
    """
    for keyword in AD_KEYWORDS:
        if keyword in review_text:
            logging.info(f"광고성 리뷰 필터링: '{keyword}' 감지")
            return None  # 이 리뷰는 분석에서 제외
    
    # 기본 클렌징
    text = re.sub(r'\s+', ' ', review_text).strip()
    text = re.sub(r'[^\w\s\.,!?]', '', text)
    
    return text if len(text) >= 10 else None  # 너무 짧은 리뷰도 제외
```

**공정성 메커니즘 2: IQR 기반 이상치 클리핑**

4부에서 자세히 다뤘지만, 카드 매출 랭킹에서 IQR 클리핑은 공정성의 문제이기도 합니다. 대형 연회장이나 뷔페 식당이 단순히 매출 규모가 크다는 이유로 소규모 맛집보다 항상 높은 점수를 받는다면, 랭킹 시스템은 대형 업장에 편향됩니다. IQR 클리핑은 매출 규모의 차이를 조정하여 "실제로 잘 되는 식당"인지 "본질적으로 규모가 큰 식당"인지를 분리합니다.

**공정성 메커니즘 3: 실내/외/불명 3분류 — 이진법 강요 거부**

AI 분류 모델이 실내/실외 여부를 판단할 때, "확실하지 않으면 한 쪽으로 결정해야 한다"는 식의 강제 이진 분류는 공정하지 않습니다. LALA는 "불명(unknown)" 카테고리를 명시적으로 유지합니다:

```python
# 실내/외 분류 결과
LOCATION_TYPES = {
    "indoor": "실내",    # 명확히 실내 (박물관, 식당 등)
    "outdoor": "실외",   # 명확히 실외 (공원, 광장 등)  
    "unknown": "불명"    # 복합 공간 또는 분류 불가
}

# 날씨 추천 로직에서 "unknown"은 실외 경고를 보내지 않음
# (실내인지 불명확한 장소에서 "강풍 경보" 띄우는 것은 과잉 알림)
def should_show_weather_warning(location_type: str, weather_flags: dict) -> bool:
    if location_type == "indoor":
        return False  # 실내는 날씨 무관
    if location_type == "unknown":
        return False  # 불명확할 때는 경보 생략 (False Positive 방지)
    # outdoor일 때만 날씨 플래그 확인
    return any(weather_flags.values())
```

---

### 원칙 3: 책임성 (Accountability) — "누가, 언제, 무엇을 했는가"

책임성은 AI 시스템의 행동과 그 결과에 대한 추적 가능성을 의미합니다. LALA는 `user_action_log` 테이블에 모든 중요 상호작용을 기록합니다:

```sql
-- sql/ddl/user_action_log.sql
CREATE TABLE locallink.user_action_log (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,      -- 익명화된 세션 식별자
    action_type VARCHAR(50) NOT NULL,     -- 'docent_request', 'place_search', 'audio_play'
    attraction_id INTEGER REFERENCES locallink.gg_tourist_attractions(id),
    language VARCHAR(10),
    created_at TIMESTAMPTZ DEFAULT NOW()
    -- 주의: 개인 식별 정보(이름, 이메일, 디바이스 ID) 없음
);
```

`session_id`는 랜덤 UUID로 생성되어 특정 개인을 식별할 수 없습니다. 그러나 동일 세션 내 행동 흐름(어떤 장소를 검색했는지, 어떤 언어로 도슨트를 요청했는지)은 추적 가능합니다. 이것은 "기능 개선을 위한 집계 분석은 가능하되, 개인 추적은 불가능한" 균형을 의도한 설계입니다.

```python
# 도슨트 요청 시 행동 로그 기록
cursor.execute("""
    INSERT INTO locallink.user_action_log 
        (session_id, action_type, attraction_id, language)
    VALUES (%s, 'docent_request', %s, %s)
""", (session_id, attraction_id, language))
```

Power BI 대시보드에서는 이 로그를 집계하여 **DAU(일간 활성 사용자 수), 언어별 사용 비율, 인기 관광지 순위**를 운영팀이 모니터링할 수 있습니다. 개인 추적 없이 서비스 품질을 개선하는 것이 목표입니다.

---

### 원칙 4: 신뢰성 (Reliability) — "AI가 실패해도 서비스는 계속된다"

신뢰성은 AI 시스템이 예상 가능하고 일관되게 작동해야 한다는 것입니다. LALA의 핵심 신뢰성 메커니즘은 **폴백(Fallback) 아키텍처**입니다:

```python
# src/frontend/web/services/docent_service.py

async def get_docent_script(
    attraction_id: int,
    language: str
) -> DocentScriptResult:
    """도슨트 스크립트 생성 (신뢰성 3단계 보장)"""
    
    # --- 1단계: 캐시 확인 ---
    cached = _load_cached_script(attraction_id, language)
    if cached:
        return DocentScriptResult(
            script_text=cached["script"],
            source="cache",
            cache_age_hours=cached["age_hours"]
        )
    
    # --- 2단계: LLM 생성 (타임아웃 + 재시도) ---
    try:
        timeout = int(os.getenv("DOCENT_LLM_TIMEOUT_SEC", "6"))  # 환경 변수로 조정 가능
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                script = await asyncio.wait_for(
                    _generate_with_llm(attraction_id, language),
                    timeout=timeout
                )
                # 성공 시 캐시 저장 후 반환
                _save_to_cache(attraction_id, language, script)
                return DocentScriptResult(script_text=script, source="llm")
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    logging.warning(f"LLM 타임아웃 재시도 {attempt+1}/{max_retries}")
                    continue
                raise
    
    except Exception as e:
        logging.error(f"LLM 생성 실패: {e}", exc_info=True)
        
        # --- 3단계: 폴백 스크립트 ---
        fallback = _get_fallback_script(attraction_id, language)
        return DocentScriptResult(
            script_text=fallback,
            source="fallback"
        )
```

이 3단계 설계의 핵심 아이디어는 **"서비스 중단은 절대 없다"**는 것입니다. LLM API가 장애 상태이거나, 타임아웃이 발생하거나, 예상치 못한 오류가 발생하더라도, 사용자는 항상 무언가를 받습니다. `source="fallback"`이 전달될 때 투명성 원칙에 따라 UI에서 안내가 표시됩니다.

**왜 타임아웃을 6초로 설정했는가?**

모바일 앱에서 사용자가 "도슨트 시작" 버튼을 누르고 6초 이상 기다리는 것은 인내의 한계에 도달하는 시점입니다. UX 연구에 따르면 응답이 3초를 넘으면 이탈률이 급격히 증가합니다. 그러나 RAG 파이프라인의 특성상(벡터 검색 + LLM 추론) 3초 내 완료는 현실적으로 어렵습니다. OS 환경에서 6초를 타임아웃으로 설정하고, 이를 환경 변수(`DOCENT_LLM_TIMEOUT_SEC`)로 관리하여 운영 중 튜닝이 가능하도록 했습니다.

---

### 원칙 5: 개인정보보호 (Privacy) — "위치 정보는 동의 후에만"

개인정보보호 원칙은 사용자의 데이터를 수집하고 사용하는 방식에 관한 것입니다. LALA는 서비스 특성상 사용자의 실시간 위치 정보가 핵심 데이터입니다. 이 위치 데이터를 어떻게 다루는지가 프라이버시 설계의 핵심입니다:

**위치 정보 수집 원칙**:
1. **동의 우선**: iOS 앱 최초 실행 시 위치 정보 수집 목적을 명확히 설명하고 동의를 받습니다.
2. **최소 수집**: 주변 명소 검색에 필요한 위도/경도만 수집하며, 이동 경로나 과거 위치는 저장하지 않습니다.
3. **비식별화**: 서버에 전송된 위치 정보는 `session_id`와 함께 처리되어 특정 개인과 연결되지 않습니다.

```swift
// iOS 위치 권한 요청 (명확한 목적 설명)
let locationManager = CLLocationManager()
locationManager.requestWhenInUseAuthorization()
// NSLocationWhenInUseUsageDescription in Info.plist:
// "현재 위치 기반으로 주변 관광지와 맛집을 추천해드립니다. 
//  위치 정보는 서버에 임시 전송되며, 이동 경로는 저장되지 않습니다."
```

```python
# Flask API: 위치 정보 처리 방식
@ios_api.route("/v1/places/nearby", methods=["POST"])
def get_nearby_places():
    data = request.get_json()
    
    # 클라이언트에서 받은 위치 정보 (즉시 처리, 장기 저장 없음)
    lat = data["latitude"]
    lng = data["longitude"]
    session_id = data.get("session_id", str(uuid.uuid4()))
    
    # 주변 명소 검색 (PostGIS 반경 쿼리)
    places = query_nearby_attractions(lat, lng, radius_km=2.0)
    
    # 행동 로그: session_id만 기록 (위치 좌표는 기록하지 않음)
    log_user_action(session_id, action_type="place_search")
    
    return jsonify({"places": places, "session_id": session_id})
```

---

### 원칙 6: 포용성 (Inclusiveness) — "모든 언어로, 모든 사람에게"

포용성 원칙은 AI 시스템이 가능한 많은 사람에게 접근 가능해야 한다는 것입니다. LALA의 포용성 구현은 두 층위로 나뉩니다:

**언어적 포용성 — 3개 언어 TTS 지원**

```python
# 지원 언어 및 Azure TTS 음성 매핑
LANGUAGE_VOICE_MAP = {
    "ko": "ko-KR-SunHiNeural",     # 한국어 - 선희 (여성 뉴럴 음성)
    "en": "en-US-JennyNeural",     # 영어 - Jenny (여성 뉴럴 음성)
    "ja": "ja-JP-NanamiNeural",    # 일본어 - なな実 (여성 뉴럴 음성)
}

# GPT-4o-mini 도슨트 스크립트 생성 시 language 파라미터 전달
# 동일한 장소에 대해 각 언어로 별도 스크립트 생성 및 캐싱
```

경기도 관광지를 방문하는 외국인 중 가장 많은 비중을 차지하는 것은 중국어권과 일본어권 방문객입니다. 영어 지원은 비영어권 방문객에게도 공통 접근 수단이 됩니다. 3개 언어 지원은 완전한 커버리지가 아니지만, 1차 MVP 범위 내에서의 현실적 선택이었습니다.

**접근성 포용성 — 청각 장애 고려**

오디오 도슨트와 함께 텍스트 스크립트도 동시에 제공합니다. iOS 앱의 VoiceOver 지원을 통해 시각 장애 사용자도 인터페이스를 탐색할 수 있습니다.

---

## 2부: 보안 아키텍처 — "소스코드에 비밀은 없다"

### 왜 Key Vault인가?

많은 프로젝트에서 개발자는 편의를 위해 API 키와 데이터베이스 패스워드를 환경 변수 파일(`.env`)이나 설정 파일에 직접 저장합니다. 이 방식의 문제점:

1. **유출 위험**: `.env` 파일이 실수로 Git에 커밋되면 즉시 공개됩니다.
2. **갱신 어려움**: 키를 교체할 때 모든 서버의 환경 변수를 수동으로 업데이트해야 합니다.
3. **감사 불가**: 누가, 언제, 어떤 비밀값을 조회했는지 추적할 수 없습니다.

Azure Key Vault는 이 세 문제를 한번에 해결합니다:
- 비밀값이 코드 외부의 격리된 HSM(Hardware Security Module)에 저장됩니다.
- 키 갱신 시 Key Vault 값만 변경하면 모든 애플리케이션에 즉시 반영됩니다.
- 모든 비밀값 조회 이벤트가 Azure Monitor에 기록됩니다.

### DefaultAzureCredential 인증 체인

LALA의 인증 아키텍처는 `DefaultAzureCredential`을 기반으로 합니다. 이것이 중요한 이유는 **환경에 따라 자동으로 최적의 인증 방법을 선택**하기 때문입니다:

```python
# config/vault_manager.py

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

class VaultManager:
    """Azure Key Vault 시크릿 관리자
    
    인증 체인 (DefaultAzureCredential이 순서대로 시도):
    1. 환경 변수 (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)
    2. 워크로드 아이덴티티 (Kubernetes 환경)
    3. Managed Identity (Azure VM, App Service, Functions)
       - System-assigned MI: 리소스에 자동 할당된 아이덴티티
       - User-assigned MI: 수동으로 생성한 아이덴티티
    4. Azure CLI (개발자 로컬 환경: az login)
    5. Azure PowerShell
    6. Interactive Browser (최후 수단)
    
    로컬 개발: az login → Azure CLI 크리덴셜 사용
    프로덕션(App Service): System-assigned Managed Identity 사용
    → 소스코드에 자격증명 없음, .env 파일 불필요
    """
    
    VAULT_URL = "https://kv3dt1stteam2dev01.vault.azure.net/"
    
    def __init__(self):
        self._credential = DefaultAzureCredential()
        self._client = SecretClient(
            vault_url=self.VAULT_URL,
            credential=self._credential
        )
        self._cache: dict[str, str] = {}
    
    def get_secret(self, secret_name: str) -> str:
        """Key Vault에서 시크릿 조회 (메모리 캐시 포함)
        
        Key Vault API 호출은 비용과 지연이 발생하므로,
        프로세스 생존 기간 동안 메모리에 캐싱.
        애플리케이션 재시작 시 캐시 초기화.
        """
        if secret_name in self._cache:
            return self._cache[secret_name]
        
        try:
            secret = self._client.get_secret(secret_name)
            self._cache[secret_name] = secret.value
            return secret.value
        except Exception as e:
            logging.warning(f"Key Vault 조회 실패 ({secret_name}): {e}")
            # 폴백: 환경 변수에서 로드 시도
            env_key = secret_name.upper().replace("-", "_")
            env_value = os.getenv(env_key)
            if env_value:
                logging.info(f"환경 변수 폴백 사용: {env_key}")
                return env_value
            raise KeyError(f"시크릿 '{secret_name}'을 찾을 수 없음")
    
    # 편의 메서드들
    def get_db_connection_string(self) -> str:
        """PostgreSQL 연결 문자열 조합"""
        host = self.get_secret("lala-db-host")
        port = self.get_secret("lala-db-port")
        dbname = self.get_secret("lala-db-name")
        user = self.get_secret("lala-db-user")
        password = self.get_secret("lala-db-password")
        return f"host={host} port={port} dbname={dbname} user={user} password={password}"
    
    def get_openai_config(self) -> dict:
        return {
            "api_key": self.get_secret("azure-openai-key"),
            "endpoint": self.get_secret("azure-openai-endpoint"),
            "embedding_deployment": self.get_secret("azure-openai-embedding-deployment"),
            "chat_deployment": self.get_secret("azure-openai-chat-deployment"),
        }
    
    def get_speech_config(self) -> dict:
        return {
            "key": self.get_secret("azure-speech-key"),
            "region": self.get_secret("azure-speech-region"),
        }

# 싱글톤 인스턴스
vault = VaultManager()
```

**왜 환경 변수 폴백이 있는가?**

Key Vault 폴백으로 환경 변수를 유지하는 이유가 있습니다. CI/CD 파이프라인(GitHub Actions)에서 PR 테스트를 실행할 때, GitHub Secrets에 저장된 테스트용 자격증명을 환경 변수로 주입합니다. 테스트 환경에서도 Key Vault를 사용할 수 있지만, 이를 위해 GitHub Actions 러너에 Key Vault 접근 권한을 부여하는 것은 보안 복잡성을 높입니다. 환경 변수 폴백은 "프로덕션은 Key Vault, 테스트는 환경 변수"라는 명확한 계층을 만들어 줍니다.

### 역할(Role) 기반 최소 권한 원칙

Managed Identity에 부여된 Azure RBAC 권한은 최소 필요 권한(Principle of Least Privilege)을 따릅니다:

```
[App Service Managed Identity 권한 구성]

Key Vault → "Key Vault Secrets User" 역할
  - Secrets: Get, List (읽기만 가능)
  - ❌ Key & Certificate 생성/삭제 불가
  - ❌ Secrets 수정/삭제 불가

Azure Container Registry → "AcrPull" 역할
  - Docker 이미지 Pull 가능
  - ❌ Push, 이미지 삭제 불가

Azure Event Hubs → "Azure Event Hubs Data Sender" 역할 (Functions)
  - 메시지 전송만 가능

PostgreSQL → Connection String을 Key Vault에서 로드
  - DB 수준 권한은 PostgreSQL Role로 별도 관리
  - locallink 스키마 SELECT/INSERT/UPDATE 권한
  - 관리자(DDL) 권한 없음
```

이 권한 구성의 의미는, 만약 App Service가 침해(Compromise)되어도 공격자가 Key Vault에서 비밀값을 **읽을 수는** 있지만, 다른 비밀값을 심거나 Azure 리소스를 삭제하는 행위는 불가능하다는 것입니다.

---

## 3부: 인프라 코드 보안 — 컨테이너와 네트워크

### Docker 이미지 보안

```dockerfile
# Dockerfile (보안 강화 포인트)

# [1] 최소 권한 사용자 실행
FROM python:3.12-slim AS base
RUN groupadd -r lala && useradd -r -g lala lala

# [2] 슬림 이미지 사용 (공격 면 최소화)
# python:3.12 vs python:3.12-slim: 약 780MB vs 약 130MB
# 불필요한 패키지 없음 → 알려진 취약점 감소

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# [3] 비 root 사용자로 실행
USER lala

# [4] 포트는 문서화하되, EXPOSE는 힌트 (실제 바인딩은 App Service 설정)
EXPOSE 8000

# [5] gunicorn: 단일 워커, 저메모리 (App Service 무료 플랜 기반)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", 
     "--timeout", "120", "wsgi:app"]
```

**왜 1 worker 4 threads인가?**

Azure App Service 무료/F1 플랜은 60분/일의 컴퓨팅 시간 제한과 1GB RAM 제한이 있습니다. gunicorn의 worker를 늘리면 각 worker가 별도의 Python 프로세스를 생성하여 메모리를 배수로 소비합니다. 1 worker + 4 threads는 메모리 효율을 극대화하면서도 동시 요청을 처리합니다. 스레드 기반 동시성은 GIL(Global Interpreter Lock) 제약이 있지만, LALA의 요청 처리는 대부분 I/O 바운드(DB 쿼리, LLM API 호출)이므로 GIL 경쟁이 최소화됩니다.

---

## 4부: 프로젝트 회고 — What Worked, What Didn't

### What Worked Well

**Azure Functions의 서버리스 선택**

배치 파이프라인을 Azure Functions로 구현한 결정은 올바른 선택이었습니다. 3시간마다 실행되는 날씨 수집기, 매주 월요일 당근마켓 크롤러, 매일 저녁 리뷰 처리 파이프라인이 모두 인프라 관리 없이 안정적으로 실행됩니다. Consumption 플랜의 비용 효율성도 뛰어났습니다.

**pgvector과 PostGIS의 공존**

단일 PostgreSQL 인스턴스에서 벡터 유사도 검색(pgvector)과 공간 반경 검색(PostGIS)을 동시에 활용하는 아키텍처는 처음에는 실험적으로 시도했지만, 결과적으로 매우 강력한 조합이었습니다. "2km 반경 내에서 + 리뷰 감성이 유사한 + 날씨가 맞는" 장소 쿼리를 단일 SQL로 처리할 수 있다는 것은 아키텍처의 큰 강점이었습니다.

**TTS 멀티랭귀지 도슨트**

한국어, 영어, 일본어 음성 도슨트를 제공하는 기능은 사용자 피드백에서 가장 긍정적인 반응을 얻었습니다. 기술적 구현은 비교적 단순했지만(Azure Cognitive Services의 뉴럴 음성 3개 적용), 사용자 경험에 미치는 임팩트는 상당했습니다.

**Key Vault + Managed Identity 아키텍처**

"소스코드에 비밀 없음" 원칙을 처음부터 설계에 포함한 것은 보안 측면에서 매우 중요한 결정이었습니다. 팀원들이 코드를 공유하고 GitHub에 push할 때도 실수로 API 키를 유출할 위험이 없었습니다.

---

### What Could Be Better

**임베딩 캐시 전략의 한계**

현재 구현에서 리뷰 임베딩은 `review_pipeline_func`가 실행될 때마다 새 리뷰에 대해서만 생성됩니다. 그러나 기존에 임베딩이 생성된 리뷰가 수정되거나 삭제될 경우, 벡터 인덱스가 즉시 업데이트되지 않습니다. PostgreSQL의 `ON DELETE CASCADE`와 `UPDATE` 트리거를 통한 임베딩 무효화 로직이 필요합니다.

**LLM 비용 모니터링 미흡**

Azure OpenAI API 비용은 토큰 단위로 과금됩니다. 현재 구현에서 `generate_embeddings_batch()`가 배치 처리로 비용을 절감하고 있지만, 실제 일별 API 비용 추적과 예산 알림 설정이 Power BI 대시보드에 포함되지 않았습니다. Azure Cost Management 알림을 API별로 분리 추적하는 기능이 추가되어야 합니다.

**Test Coverage 부족**

RAG 파이프라인과 같은 LLM 기반 코드의 자동화 테스트는 어렵습니다. LLM 출력이 비결정론적이기 때문에 "정확한 출력"을 테스트하기 어렵고, 실제 Azure OpenAI API 호출은 CI 비용을 발생시킵니다. Mock 기반의 단위 테스트와 실제 API 호출을 사용하는 통합 테스트의 분리가 필요합니다. 현재는 `tests/unit/`에 핵심 서비스 코드의 단위 테스트가 일부 존재하지만, 커버리지가 불충분합니다.

**리뷰 데이터 다양성 확보**

당근마켓 크롤러는 현재 주요 경기도 도시(수원, 성남, 용인, 고양)의 맛집 언급 데이터를 수집합니다. 그러나 당근마켓의 지역 커버리지는 도시 지역에 편중되어 있어, 농촌 지역이나 소도시의 식당은 `daangn_score=0`으로 불이익을 받을 수 있습니다. 이것은 공정성 원칙과도 연결되는 미해결 문제입니다. 네이버 지도 리뷰, 카카오맵 데이터 등 다양한 소스를 추가하는 것이 필요합니다.

---

## 5부: 다음 단계 — Phase 2의 청사진

이 프로젝트를 마치며, 다음 단계에서 구현하고 싶은 것들을 정리합니다:

### 기술적 확장

```
[Phase 2 아키텍처 후보 개선 사항]

1. Multi-modal RAG
   현재: 텍스트 리뷰 → 텍스트 임베딩 → 텍스트 도슨트
   확장: 관광지 이미지 → Vision 임베딩 → 이미지+텍스트 멀티모달 도슨트
   기술: Azure OpenAI Vision API + CLIP 임베딩

2. 실시간 개인화
   현재: 방문 이력 없는 일괄 추천
   확장: session 내 이동 경로 + 방문 이력 기반 개인화 추천
   기술: Azure Cache for Redis + collaborative filtering

3. 대화형 도슨트
   현재: 단방향 스크립트 전달
   확장: iOS 앱에서 음성으로 질문 → AI가 음성으로 답변
   기술: Azure Speech To Text + GPT-4o multi-turn conversation

4. 더 많은 언어 지원
   현재: 한국어, 영어, 일본어
   확장: 중국어(간체/번체), 베트남어, 태국어
   타겟: 경기도 방문 외국인 상위 5개국 커버
```

### 비즈니스 확장

LALA가 단순한 관광 정보 앱을 넘어 "지역 경제와 연결된 AI 관광 플랫폼"이 되려면, 지역 소상공인이 자신의 가게 정보를 직접 업데이트하고 AI 도슨트 스크립트를 검토/수정할 수 있는 **파트너 대시보드**가 필요합니다. 이것은 투명성 원칙(사업자도 AI가 자신의 가게를 어떻게 소개하는지 알 권리)과 공정성 원칙(사업자가 오정보를 수정할 기회)을 동시에 구현합니다.

---

## 에필로그 — 기술 블로그 시리즈를 마치며

5편에 걸쳐 LALA 프로젝트의 기술적 여정을 기록했습니다. 요약하면:

| 편 | 핵심 메시지 |
|----|-------------|
| 1편 | "왜 Azure PostgreSQL인가" — 적정 기술 선택의 논리 |
| 2편 | "배치와 실시간의 분리" — 이벤트 드리븐 아키텍처의 힘 |
| 3편 | "PostGIS + pgvector = 공간 × 의미" — 단일 DB에서 두 세계 |
| 4편 | "점검중이 파이프라인을 멈췄다" — 공공 데이터의 불완전성과 방어 설계 |
| 5편 | "AI 윤리는 코드다" — 원칙을 함수로, 보안을 아키텍처로 |

이 프로젝트를 통해 기술적으로 성장하는 것 이상의 것을 배웠습니다. AI 서비스를 "만드는 것"과 "책임지는 것"은 다릅니다. 코드를 배포하는 순간, 그것은 실제 사람들의 경험에 영향을 미칩니다. 경기도를 방문한 외국인 관광객이 LALA의 AI 도슨트 덕분에 몰랐던 골목 식당을 발견하고, 그 경험을 자국의 친구들에게 이야기한다면, 그것이 이 코드가 세상에 미치는 긍정적인 흔적입니다. 그 흔적을 책임감 있게 남기는 것이 엔지니어의 의무라고 생각합니다.

---

> **시리즈 완결**  
> [1부 — 배경과 아키텍처](./01_Background_and_Architecture_Design.md)  
> [2부 — 데이터 파이프라인](./02_Data_Pipeline_Batch_and_Realtime.md)  
> [3부 — RAG와 pgvector](./03_RAG_and_Pgvector_Implementation.md)  
> [4부 — 트러블슈팅](./04_Troubleshooting_PCS_Framework.md)  
> **5부 — AI 윤리와 보안** (현재 페이지)
