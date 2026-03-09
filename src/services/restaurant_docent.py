"""경기도 지역 맛집 TOP N 통합 스토리텔링 도슨트

여러 식당을 단순 나열이 아닌 하나의 '지역 맛집 투어 가이드' 내러티브로 연결합니다.

주요 함수:
  rank_restaurants()                  : 카드 매출 + 당근 언급수 기반 IQR 보정 가중치 랭킹
  fetch_tour_context()                : DB에서 각 식당 컨텍스트 수집
  generate_tour_script()              : Azure OpenAI LLM으로 통합 스토리텔링 대본 생성
  synthesize_tour_audio()             : speech_service REST TTS로 MP3 바이트 반환
  generate_restaurant_tour_docent()   : 전체 파이프라인

설계 원칙:
  - TTS: azure.cognitiveservices.speech SDK 대신 speech_service.synthesize_speech_mp3 사용
    (REST 직접 호출 → MP3 bytes 반환 → 웹 API 친화적, SDK 설치 불필요, SSML 음질 우수)
  - LLM 인증: 환경변수 우선 → vault_manager 폴백 (docent_service.py 패턴)
  - 하드코딩 경로 없음: 파일 저장은 호출자가 결정, 함수는 bytes/str만 반환
  - DB 컨텍스트: restaurant_details(요약/분위기/팁) 우선,
    없으면 restaurant_reviews + gg_restaurant_info 폴백
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from openai import AzureOpenAI

logger = logging.getLogger(__name__)

_VALID_LANGUAGES = {"ko", "en"}
_LLM_DEFAULT_TIMEOUT: float = 15.0   # 단일 장소(6s)보다 긴 2분 대본용
_LLM_DEFAULT_MAX_TOKENS: int = 2000  # ~2분 분량 오디오 대본


# ==============================================================================
# 헬퍼: 환경변수 파싱
# ==============================================================================

def _float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        return float(raw) if raw else default
    except Exception:
        return default


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except Exception:
        return default



# ==============================================================================
# 반환 타입
# ==============================================================================

@dataclass
class TourDocentResult:
    """지역 맛집 투어 도슨트 생성 결과."""

    restaurant_names: list[str]
    language: str
    script: str
    audio_bytes: bytes | None = None
    source: str = "llm"       # "llm" | "fallback"
    restaurant_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.restaurant_count = len(self.restaurant_names)


# ==============================================================================
# LLM 클라이언트  (docent_service.py 환경변수 → vault 폴백 패턴)
# ==============================================================================

def _get_llm_client() -> tuple[AzureOpenAI, str]:
    """(AzureOpenAI client, deployment_name) 반환. 설정 없으면 RuntimeError."""
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
    api_key  = (os.getenv("AZURE_OPENAI_KEY") or "").strip()
    api_ver  = (os.getenv("AZURE_OPENAI_VERSION") or "").strip()
    deploy   = (
        os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or ""
    ).strip()

    if not (endpoint and api_key and api_ver and deploy):
        try:
            from config.vault_manager import get_vault_manager
            _vm = get_vault_manager()
            endpoint = endpoint or (_vm.get_secret("azure-openai-endpoint") or "").strip()
            api_key  = api_key  or (_vm.get_secret("azure-openai-key")      or "").strip()
            api_ver  = api_ver  or (_vm.get_secret("azure-openai-version")   or "").strip()
            deploy   = deploy   or (_vm.get_secret("azure-openai-deployment-name") or "").strip()
        except Exception:
            pass

    if not (endpoint and api_key and api_ver and deploy):
        raise RuntimeError(
            "Azure OpenAI 설정 정보(endpoint/key/version/deployment)가 없습니다."
        )

    timeout = max(5.0, min(_float_env("DOCENT_TOUR_LLM_TIMEOUT_SEC", _LLM_DEFAULT_TIMEOUT), 60.0))
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_ver,
        max_retries=0,
        timeout=timeout,
    )
    return client, deploy


# ==============================================================================
# STEP 1: 랭킹  (process_restaurants.py IQR + 가중치 스코어 로직 이식)
# ==============================================================================

def rank_restaurants(candidate_names: list[str], cursor) -> list[str]:
    """카드 매출 40% + 당근 언급 60% 가중 스코어로 정렬된 상위 10개 이름 반환.

    IQR 이상치 보정 → Min-Max 정규화 → 가중합 (process_restaurants.py 동일 로직).
    DB 조회 실패 시 입력 순서 그대로 반환.
    """
    if not candidate_names:
        return []

    try:
        import pandas as pd

        cursor.execute(
            """
            WITH TargetList AS (
                SELECT unnest(%s::text[]) AS target_name
            ),
            TargetInfo AS (
                SELECT t.target_name AS bizplc_nm, r.sigun_nm, r.bizcond_div_nm_info
                FROM TargetList t
                LEFT JOIN locallink.gg_restaurant_info r ON t.target_name = r.bizplc_nm
            )
            SELECT
                ti.bizplc_nm                          AS restaurant_name,
                COALESCE(c.total_amt, 0)              AS card_score_raw,
                COALESCE(d.total_mention, 0)          AS daangn_score_raw
            FROM TargetInfo ti
            LEFT JOIN locallink.v_card_stats_summary c
                   ON ti.sigun_nm = c.city AND ti.bizcond_div_nm_info = c.category
            LEFT JOIN daangn.v_daangn_stats_summary d
                   ON ti.bizplc_nm = d.place_name AND ti.sigun_nm = d.city_name
            """,
            (candidate_names,),
        )
        rows = cursor.fetchall()
        if not rows:
            return candidate_names[:10]

        df = pd.DataFrame(
            rows, columns=["restaurant_name", "card_score_raw", "daangn_score_raw"]
        )

        # IQR Capping — 카드 매출 이상치가 전체 랭킹을 왜곡하는 것을 방지
        q1, q3 = df["card_score_raw"].quantile([0.25, 0.75])
        df["card_score_raw"] = df["card_score_raw"].clip(upper=q3 + 1.5 * (q3 - q1))

        # Min-Max 정규화
        for raw_col, norm_col in [("card_score_raw", "norm_card"), ("daangn_score_raw", "norm_daangn")]:
            lo, hi = df[raw_col].min(), df[raw_col].max()
            df[norm_col] = (df[raw_col] - lo) / (hi - lo) if hi > lo else 0.0

        # 가중합: 카드 40% + 당근 60%
        df["final_score"] = df["norm_card"] * 0.4 + df["norm_daangn"] * 0.6
        return df.sort_values("final_score", ascending=False)["restaurant_name"].head(10).tolist()

    except Exception as exc:
        logger.warning("rank_restaurants 쿼리 실패, 입력 순서 그대로 사용: %s", exc)
        return candidate_names[:10]


# ==============================================================================
# STEP 2: DB 컨텍스트 조회
# ==============================================================================

def _fetch_single_restaurant_context(cursor, name: str) -> dict[str, Any]:
    """restaurant_details(분석 데이터) 우선 → gg_restaurant_info + restaurant_reviews 폴백."""
    ctx: dict[str, Any] = {
        "name": name,
        "region": "",
        "biz_type": "",
        "address": "",
        "summary_ko": "",
        "atmosphere": "",
        "tips": "",
        "keywords": "",
        "review_snippet": "",
    }

    # 1) restaurant_details — process_restaurants.py가 채운 LLM 분석 결과
    try:
        cursor.execute(
            """
            SELECT summary_ko, atmosphere_ko, tips_ko
            FROM locallink.restaurant_details
            WHERE restaurant_name = %s
            LIMIT 1
            """,
            (name,),
        )
        row = cursor.fetchone()
        if row:
            ctx["summary_ko"] = (row["summary_ko"]    or "").strip()
            ctx["atmosphere"] = (row["atmosphere_ko"] or "").strip()
            ctx["tips"]       = (row["tips_ko"]       or "").strip()
    except Exception:
        pass

    # 2) gg_restaurant_info — 업종, 주소, 지역
    try:
        cursor.execute(
            """
            SELECT sigun_nm, bizcond_div_nm_info,
                   COALESCE(refine_roadnm_addr, refine_lotno_addr, '') AS address
            FROM locallink.gg_restaurant_info
            WHERE bizplc_nm = %s
            LIMIT 1
            """,
            (name,),
        )
        row = cursor.fetchone()
        if row:
            ctx["region"]   = (row["sigun_nm"]           or "").strip()
            ctx["biz_type"] = (row["bizcond_div_nm_info"] or "").strip()
            ctx["address"]  = (row["address"]             or "").strip()
    except Exception:
        pass

    # 3) restaurant_reviews — summary가 없을 때 키워드 + 리뷰 스니펫으로 보충
    if not ctx["summary_ko"]:
        try:
            cursor.execute(
                """
                SELECT extracted_keywords, clean_text
                FROM locallink.restaurant_reviews
                WHERE restaurant_name = %s
                ORDER BY id DESC
                LIMIT 2
                """,
                (name,),
            )
            rows = cursor.fetchall()
            if rows:
                ctx["keywords"] = (rows[0]["extracted_keywords"] or "").strip()
                ctx["review_snippet"] = " / ".join(
                    (r["clean_text"] or "")[:120]
                    for r in rows
                    if (r["clean_text"] or "").strip()
                )
        except Exception:
            pass

    return ctx


def fetch_tour_context(restaurant_names: list[str], cursor) -> list[dict[str, Any]]:
    """식당 이름 리스트 → 각 식당의 컨텍스트 dict 리스트 반환."""
    return [_fetch_single_restaurant_context(cursor, name) for name in restaurant_names]


# ==============================================================================
# STEP 3: 통합 스토리텔링 대본 생성
# ==============================================================================

def _build_context_block(ctx: dict[str, Any]) -> str:
    """단일 식당 컨텍스트 → 프롬프트용 텍스트 블록."""
    lines = [f"[{ctx['name']}]"]
    if ctx["region"]:
        lines.append(f"- 지역: {ctx['region']}")
    if ctx["biz_type"]:
        lines.append(f"- 업종: {ctx['biz_type']}")
    if ctx["summary_ko"]:
        lines.append(f"- 요약: {ctx['summary_ko']}")
    if ctx["atmosphere"]:
        lines.append(f"- 분위기: {ctx['atmosphere']}")
    if ctx["tips"]:
        lines.append(f"- 팁: {ctx['tips']}")
    if ctx["keywords"]:
        lines.append(f"- 키워드: {ctx['keywords']}")
    if ctx["review_snippet"]:
        lines.append(f"- 리뷰: {ctx['review_snippet']}")
    return "\n".join(lines)


def generate_tour_script(
    restaurant_names: list[str],
    context_list: list[dict[str, Any]],
    language: str,
) -> str:
    """Azure OpenAI LLM으로 통합 맛집 투어 가이드 대본을 생성합니다."""
    if language not in _VALID_LANGUAGES:
        raise ValueError("language must be 'ko' or 'en'")

    full_context = "\n\n".join(_build_context_block(ctx) for ctx in context_list)
    count = len(restaurant_names)

    if language == "ko":
        system_message = (
            "당신은 'LALA AI Guide', 경기도 근처 맛집을 소개하는 전문 오디오 투어 도슨트입니다.\n"
            "[대본 작성 원칙]\n"
            f"1. 내러티브 구조: {count}개 식당을 하나의 여정으로 — 단순 나열 금지. "
            "   분위기·메뉴 특성에 따라 흐름 있게 연결하세요.\n"
            "2. 구성: 도입(지역 소개 + 기대감 조성) → 음식 여정(각 식당을 스토리로 이어줌)"
            "   → 마무리(방문 독려)\n"
            "3. 데이터 기반: 키워드·요약·분위기 정보를 문장에 자연스럽게 녹여 생생함을 더하세요.\n"
            "4. 말투: 이어폰으로 듣는 오디오 가이드 — 리듬감 있는 구어체, 청자에게 직접 말하는 형식.\n"
            "5. 없는 사실을 지어내지 마세요.\n"
            "6. 분량: 약 2분 분량(300~400 단어).\n"
            "7. [필수] 반드시 한국어로만 작성하세요. 영어를 사용하면 안 됩니다."
        )
        user_message = (
            f"아래 TOP {count}개 맛집 데이터를 바탕으로 통합 오디오 투어 가이드 대본을 한국어로 작성해주세요.\n\n"
            f"{full_context}"
        )
    else:
        system_message = (
            "You are 'LALA AI Guide', a professional audio tour docent introducing local restaurants near Gyeonggi-do, Korea.\n"
            "[Script Guidelines]\n"
            f"1. Narrative structure: Connect {count} restaurants as one journey — no simple listing. "
            "   Link them by atmosphere and menu characteristics.\n"
            "2. Structure: Intro (region intro + anticipation) → Food journey (each restaurant as a story) → Closing (encourage visit)\n"
            "3. Data-driven: Weave keywords, summaries, and atmosphere info naturally into sentences.\n"
            "4. Tone: Audio guide listened through earphones — rhythmic conversational style, speak directly to the listener.\n"
            "5. Do not fabricate facts.\n"
            "6. Length: ~2 minutes (~300-400 words).\n"
            "7. [REQUIRED] Write entirely in English. Do not use Korean."
        )
        user_message = (
            f"Based on the TOP {count} restaurant data below, write a unified audio tour guide script in English.\n\n"
            f"{full_context}"
        )

    max_tokens = _int_env("DOCENT_TOUR_MAX_TOKENS", _LLM_DEFAULT_MAX_TOKENS)
    client, deploy = _get_llm_client()
    response = client.chat.completions.create(
        model=deploy,
        temperature=0.7,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user",   "content": user_message},
        ],
    )
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("LLM이 빈 대본을 반환했습니다.")
    return content


def _fallback_tour_script(restaurant_names: list[str], language: str) -> str:
    """LLM 실패 시 기본 안내 대본."""
    names_str = ", ".join(restaurant_names[:5])
    tail = " and more." if len(restaurant_names) > 5 else "."
    if language == "en":
        return (
            f"Welcome to your local restaurant tour! "
            f"Today we recommend: {names_str}{tail} "
            "Please check each restaurant's hours before visiting."
        )
    tail_ko = " 외 여러 곳입니다." if len(restaurant_names) > 5 else "입니다."
    return (
        f"안녕하세요, LALA 맛집 투어 가이드입니다. "
        f"오늘 추천 맛집은 {names_str}{tail_ko} "
        "방문 전 영업시간을 꼭 확인해 주세요."
    )


# ==============================================================================
# STEP 4: TTS — speech_service REST 방식 (SDK 불필요, MP3 bytes 반환)
# ==============================================================================

def synthesize_tour_audio(script: str, language: str) -> bytes:
    """speech_service.synthesize_speech_mp3로 MP3 bytes를 반환합니다.

    azure.cognitiveservices.speech SDK 대신 Azure Speech REST API를 직접 호출합니다:
      - 추가 패키지 설치 불필요
      - MP3 bytes 반환 → 웹 API에서 바로 Response로 streaming 가능
      - SSML 기반으로 음성 품질이 우수
    """
    from src.frontend.web.services.speech_service import synthesize_speech_mp3
    return synthesize_speech_mp3(script=script, language=language)


# ==============================================================================
# 통합 파이프라인
# ==============================================================================

def generate_restaurant_tour_docent(
    restaurant_names: list[str],
    cursor,
    language: str = "ko",
    with_audio: bool = True,
    auto_rank: bool = False,
) -> TourDocentResult:
    """지역 맛집 TOP N 통합 스토리텔링 도슨트를 생성합니다.

    Args:
        restaurant_names: 이미 선별된 식당명 리스트 (최대 10개 권장).
        cursor:           psycopg2 DictCursor (트랜잭션 관리는 호출자가 담당).
        language:         "ko" | "en"
        with_audio:       True면 MP3 bytes도 생성 (TTS API 비용 발생).
        auto_rank:        True면 rank_restaurants()로 정렬 후 상위 10개만 사용.

    Returns:
        TourDocentResult (script, audio_bytes, restaurant_names, language, source)
    """
    if language not in _VALID_LANGUAGES:
        raise ValueError("language must be 'ko' or 'en'")
    if not restaurant_names:
        raise ValueError("restaurant_names가 비어 있습니다.")

    names = restaurant_names
    if auto_rank:
        names = rank_restaurants(names, cursor)
    names = names[:10]

    context_list = fetch_tour_context(names, cursor)

    script = ""
    source = "fallback"
    try:
        script = generate_tour_script(names, context_list, language)
        source = "llm"
    except Exception as exc:
        logger.warning(
            "tour_docent LLM 실패 (count=%d language=%s): %s",
            len(names), language, exc,
        )
        script = _fallback_tour_script(names, language)

    audio_bytes: bytes | None = None
    if with_audio and script:
        try:
            audio_bytes = synthesize_tour_audio(script, language)
        except Exception as exc:
            logger.warning("tour_docent TTS 실패: %s", exc)

    return TourDocentResult(
        restaurant_names=names,
        language=language,
        script=script,
        audio_bytes=audio_bytes,
        source=source,
    )


# ==============================================================================
# CLI 테스트 진입점 (restaurant_main.py 파이프라인과 동일한 흐름)
# ==============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from dotenv import load_dotenv
    import psycopg2
    import psycopg2.extras
    from config.vault_manager import get_vault_manager

    load_dotenv()
    _vm = get_vault_manager()

    # restaurant_main.py와 동일한 파이프라인으로 동작 확인
    GPS_LAT, GPS_LON = 37.2807, 127.0151

    print("\n" + "🚀 " * 20)
    print("LALA RESTAURANT TOUR DOCENT: 통합 파이프라인 테스트")
    print("🚀 " * 20)

    from src.collectors.restaurant_filter import filter_restaurants_by_location
    from src.collectors.process_restaurants import get_ranked_restaurants

    # STEP 1: 위치 기반 필터링
    restaurants, status = filter_restaurants_by_location(radius_m=1500, lat=GPS_LAT, lon=GPS_LON)
    if not restaurants:
        print(f"⚠️ 주변 식당 없음: {status}")
        sys.exit(0)

    # STEP 2: 가중치 랭킹 (process_restaurants.py의 get_ranked_restaurants 활용)
    candidates = [{"restaurant_name": r[0]} for r in restaurants]
    ranked_df = get_ranked_restaurants(candidates)
    top_names = (
        ranked_df["restaurant_name"].tolist()
        if not ranked_df.empty
        else [r[0] for r in restaurants[:10]]
    )
    print(f"\n✅ TOP {len(top_names)} 선정: {top_names}")

    # STEP 3: 투어 도슨트 생성
    conn = psycopg2.connect(_vm.get_db_dsn())
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            result = generate_restaurant_tour_docent(
                restaurant_names=top_names,
                cursor=cur,
                language="ko",
                with_audio=True,
            )
        conn.commit()
    finally:
        conn.close()

    print(f"\n🌟 [SOURCE: {result.source}] {result.restaurant_count}개 식당 대본 생성 완료")
    print("-" * 60)
    print(result.script[:400] + ("..." if len(result.script) > 400 else ""))

    if result.audio_bytes:
        out_path = Path("data/docent/mp3/restaurant_tour.mp3")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(result.audio_bytes)
        print(f"\n✅ MP3 저장: {out_path}  ({len(result.audio_bytes):,} bytes)")
    else:
        print("\n⚠️ 음성 생성 실패 또는 with_audio=False")

# ==============================================================================
# 1. RAG: DB에서 TOP 10 식당 데이터 일괄 추출 (기존 로직 유지)
# ==============================================================================
def fetch_top10_context(restaurant_list):
    """리스트에 담긴 10개 식당의 키워드와 리뷰를 DB에서 가져옵니다."""
    conn = psycopg2.connect(vault.get_db_dsn())
    
    combined_data = []
    try:
        with conn.cursor() as cursor:
            for name in restaurant_list:
                query = """
                    SELECT extracted_keywords, clean_text 
                    FROM locallink.restaurant_details 
                    WHERE restaurant_name = %s
                    LIMIT 2;
                """
                cursor.execute(query, (name,))
                rows = cursor.fetchall()
                if rows:
                    keywords = rows[0][0]
                    reviews = " / ".join([row[1][:150] for row in rows])
                    combined_data.append(f"[{name}]\n- Keywords: {keywords}\n- Insights: {reviews}")
        
        return "\n\n".join(combined_data)
    finally:
        conn.close()

# ==============================================================================
# 2. 통합 도슨트 대본 생성 (Azure OpenAI gpt-4o-mini 활성화)
# ==============================================================================
def generate_integrated_docent_script(restaurant_list, language="English"):
    """Azure OpenAI를 사용하여 통합 오디오 가이드 대본을 생성합니다."""
    # 리소스 로드
    azure_client = get_db_and_llm_resources()
    
    # 1. DB 컨텍스트 확보
    full_context = fetch_top10_context(restaurant_list)
    
    if not full_context:
        return "⚠️ DB에서 식당 데이터를 찾을 수 없습니다."

    system_prompt = f"""
    당신은 'LALA AI Guide'입니다. 현재 위치 주변 맛집 TOP 10을 소개하는 전문 오디오 도슨트입니다.
    
    [대본 작성 원칙]
    1. 구성: 10개 식당을 단순히 나열하지 말고, 분위기와 메뉴 특성에 따라 자연스럽게 연결(Storytelling)하세요.
    2. 데이터 기반: 분석된 키워드와 리뷰 인사이트를 문장에 녹여내어 생생함을 더하세요.
    3. 말투: 이어폰으로 듣는 상황임을 고려하여 리듬감 있는 '구어체'를 사용하세요.
    4. 언어: 반드시 {language}로 작성하세요.
    """

    user_prompt = f"""
    [TOP 10 맛집 데이터]:
    {full_context}

    위 10개 가게를 모두 포함하여 약 2분 분량의 통합 오디오 가이드 대본을 작성해줘.
    """

    try:
        deployment_name = AZURE_OPENAI_RESTAURANT_DEPLOYMENT
        
        response = azure_client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        return response.choices[0].message.content
        
    except Exception as e:
        return f"❌ Azure OpenAI 대본 생성 실패: {str(e)}"

def text_to_speech_english(text, output_filename="eng_guide_voice.mp3"):
    """생성된 영어 대본을 미국식 영어 음성으로 변환합니다."""
    
    # 1. 설정 로드 (.env에 AZURE_SPEECH_KEY, AZURE_SPEECH_REGION 있어야 함)
    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY, 
        region=AZURE_SPEECH_REGION
    )
    
    # 2. 영어 성우 설정 (Ava는 매우 자연스럽고 친절한 목소리입니다)
    # 남성 목소리를 원하시면 "en-US-AndrewNeural"을 사용하세요.
    speech_config.speech_synthesis_voice_name = "en-US-AvaNeural"
    
    # 3. 파일 저장 설정
    full_path = os.path.join(DOCENT_OUTPUT_DIR_MP3, output_filename)
    file_config = speechsdk.audio.AudioOutputConfig(filename=full_path)
    # 4. 스피커 출력 설정 (실시간 재생)
    speaker_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
    
    # 5. 먼저 스피커로 실시간 재생
    speaker_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, 
        audio_config=speaker_config
    )
    
    print(f"🔊 [LIVE] 가이드 음성 재생 중...")
    result = speaker_synthesizer.speak_text_async(text).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"✅ 음성 재생 완료")
    else:
        print(f"❌ 실시간 재생 실패: {result.reason}")
        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"Error Details: {cancellation_details.error_details}")
    
    # 6. 재생 완료 후 파일로도 저장
    file_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, 
        audio_config=file_config
    )
    
    result = file_synthesizer.speak_text_async(text).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"✅ 가이드 파일 저장 완료: {full_path}")
    else:
        print(f"❌ 파일 저장 실패: {result.reason}")
        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"Error Details: {cancellation_details.error_details}")

# ==============================================================================
# 3. 통합 프로세스 함수 (attraction_docent와 일관성)
# ==============================================================================
def process_restaurants(restaurant_list, language="English"):
    """여러 식당의 통합 도슨트를 생성합니다."""
    print(f"\n📊 [Batch Mode] {len(restaurant_list)}개 식당 처리 중...")
    
    # 1. 대본 생성
    final_script = generate_integrated_docent_script(restaurant_list, language=language)
    
    if "❌" not in final_script:
        print("\n🌟 [DOCENT SCRIPT GENERATED] 🌟\n")
        print(final_script[:200] + "..." if len(final_script) > 200 else final_script)
        
        # 대본을 파일에 저장
        script_filename = f"restaurant_guide_{language.lower()}_script.txt"
        script_path = os.path.join(DOCENT_OUTPUT_DIR_SCRIPTS, script_filename)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(final_script)
        print(f"✅ 대본 저장 완료: {script_path}\n")
        
        # 2. 음성 파일 생성
        output_filename = f"restaurant_guide_{language.lower()}.mp3"
        text_to_speech_english(final_script, output_filename)
    else:
        print(final_script)

# ==============================================================================
# 3. 메인 실행 루프 (테스트용)
# ==============================================================================
if __name__ == "__main__":
    top10_list = [
        "무무옥", "로우파이브신풍", "사과당 수원행궁점", "달달한부엌", 
        "위해브투데이", "키프(KIFF)", "사케도로보", "킵댓 행궁점", 
        "누크녹카라멜하우스", "다담"
    ]
    
    # 1. 대본 생성 (반드시 English로 설정)
    print(f"🎙️ [Batch Mode: Azure OpenAI] {len(top10_list)} Restaurants - Generating English Script...")
    final_script = generate_integrated_docent_script(top10_list, language="English")
    
    if "❌" not in final_script:
        print("\n🌟 [ENGLISH DOCENT SCRIPT GENERATED] 🌟\n")
        print(final_script) 
        
        # 2. 음성 파일 생성
        text_to_speech_english(final_script, "food_guide_en.mp3")
    else:
        print(final_script)