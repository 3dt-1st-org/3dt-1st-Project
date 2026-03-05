from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from openai import AzureOpenAI


TTL_SECONDS = 7 * 24 * 60 * 60
logger = logging.getLogger(__name__)
_VALID_CATEGORIES = {"attraction", "restaurant", "event"}
_VALID_LANGUAGES = {"ko", "en"}
_VALID_MODES = {"brief", "detail"}
_ATTRACTION_ID_EXPR = "MD5(COALESCE(attraction_name, '') || '|' || COALESCE(sigun_nm, ''))"
_EVENT_ID_EXPR = "MD5(COALESCE(title, '') || '|' || COALESCE(url, '') || '|' || COALESCE(city, ''))"


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


@dataclass(frozen=True)
class DocentScriptResult:
    place_id: str
    category: str
    language: str
    mode: str
    script: str
    source: str
    generated_at: str
    ttl_sec: int = TTL_SECONDS


def generate_docent_script(cursor, place_id: str, category: str, language: str, mode: str) -> DocentScriptResult:
    place_id = place_id.strip()
    category = category.strip().lower()
    language = language.strip().lower()
    mode = mode.strip().lower()

    if not place_id:
        raise ValueError("place_id is required")
    if category not in _VALID_CATEGORIES:
        raise ValueError("category must be attraction|restaurant|event")
    if language not in _VALID_LANGUAGES:
        raise ValueError("language must be ko|en")
    if mode not in _VALID_MODES:
        raise ValueError("mode must be brief|detail")

    cached = _load_cached_script(cursor, place_id, category, language, mode)
    if cached is not None:
        return cached

    context = _load_context(cursor, place_id, category)

    script = ""
    source = "fallback"
    llm_error: Exception | None = None
    llm_attempts = max(1, min(_int_env("DOCENT_LLM_MAX_ATTEMPTS", 1), 2))
    for _ in range(llm_attempts):
        try:
            script = _generate_with_llm(context=context, category=category, language=language, mode=mode)
            source = "llm"
            llm_error = None
            break
        except Exception as exc:
            llm_error = exc

    if source != "llm":
        if llm_error is not None:
            logger.warning(
                "docent_llm_failed place_id=%s category=%s language=%s mode=%s error=%s",
                place_id,
                category,
                language,
                mode,
                llm_error,
            )
        script = _fallback_script(context=context, category=category, language=language, mode=mode)

    _store_cache(
        cursor,
        place_id=place_id,
        category=category,
        language=language,
        mode=mode,
        script=script,
        source=source,
    )

    return DocentScriptResult(
        place_id=place_id,
        category=category,
        language=language,
        mode=mode,
        script=script,
        source=source,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _load_cached_script(cursor, place_id: str, category: str, language: str, mode: str) -> DocentScriptResult | None:
    if not _cache_table_exists(cursor):
        return None

    try:
        cursor.execute(
            """
            SELECT script, source, created_at
            FROM locallink.docent_script_cache
            WHERE place_id = %s
              AND category = %s
              AND language = %s
              AND mode = %s
              AND expires_at > NOW()
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (place_id, category, language, mode),
        )
    except Exception:
        _safe_rollback(cursor)
        return None

    row = cursor.fetchone()
    if not row:
        return None

    cached_source = str(row["source"] or "").strip().lower()
    if cached_source == "fallback":
        # Never reuse fallback cache rows; allow next request to try LLM again.
        try:
            cursor.execute(
                """
                DELETE FROM locallink.docent_script_cache
                WHERE place_id = %s
                  AND category = %s
                  AND language = %s
                  AND mode = %s
                """,
                (place_id, category, language, mode),
            )
        except Exception:
            _safe_rollback(cursor)
        return None

    created_at = row["created_at"]
    if created_at is None:
        created_at_iso = datetime.now(timezone.utc).isoformat()
    else:
        created_at_iso = created_at.astimezone(timezone.utc).isoformat()

    return DocentScriptResult(
        place_id=place_id,
        category=category,
        language=language,
        mode=mode,
        script=row["script"],
        source="cache",
        generated_at=created_at_iso,
    )


def _store_cache(cursor, place_id: str, category: str, language: str, mode: str, script: str, source: str) -> None:
    if not _cache_table_exists(cursor):
        return

    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(seconds=TTL_SECONDS)

    try:
        cursor.execute(
            """
            INSERT INTO locallink.docent_script_cache (
                place_id,
                category,
                language,
                mode,
                script,
                source,
                created_at,
                expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (place_id, category, language, mode)
            DO UPDATE SET
                script = EXCLUDED.script,
                source = EXCLUDED.source,
                created_at = EXCLUDED.created_at,
                expires_at = EXCLUDED.expires_at
            """,
            (place_id, category, language, mode, script, source, now_utc, expires_at),
        )
    except Exception:
        _safe_rollback(cursor)
        return


def _load_context(cursor, place_id: str, category: str) -> dict[str, Any]:
    if category == "attraction":
        return _load_attraction_context(cursor, place_id)
    if category == "restaurant":
        return _load_restaurant_context(cursor, place_id)
    return _load_event_context(cursor, place_id)


def _load_attraction_context(cursor, place_id: str) -> dict[str, Any]:
    try:
        cursor.execute(
            f"""
        SELECT
            {_ATTRACTION_ID_EXPR} AS id,
            COALESCE(attraction_name, '') AS name,
            COALESCE(sigun_nm, '') AS region,
            '' AS address,
            COALESCE(overview, '') AS overview,
            COALESCE(history, '') AS history,
            COALESCE(use_time, '') AS use_time,
            COALESCE(parking, '') AS parking,
            COALESCE(closed_days, '') AS closed_days,
            COALESCE(pet_allowed, '') AS pet_allowed
        FROM locallink.attraction_descriptions
        WHERE {_ATTRACTION_ID_EXPR} = %s
        LIMIT 1
        """,
            (place_id,),
        )
    except Exception:
        _safe_rollback(cursor)
        return {"name": "이 장소", "region": "", "address": "", "category": "attraction", "facts": []}

    place = cursor.fetchone()
    if not place:
        return {"name": "이 장소", "region": "", "address": "", "category": "attraction", "facts": []}

    facts: list[str] = []
    for key in ("overview", "history", "use_time", "parking", "closed_days", "pet_allowed"):
        value = (place.get(key) or "").strip()
        if value:
            facts.append(value)

    return {
        "name": place["name"],
        "region": place["region"],
        "address": place["address"],
        "category": "attraction",
        "facts": facts,
    }


def _load_restaurant_context(cursor, place_id: str) -> dict[str, Any]:
    try:
        cursor.execute(
            """
        SELECT
            MD5(bizplc_nm || COALESCE(refine_roadnm_addr,'')) AS id,
            COALESCE(bizplc_nm, '') AS name,
            COALESCE(sigun_nm, '') AS region,
            COALESCE(refine_roadnm_addr, refine_lotno_addr, '') AS address,
            COALESCE(bizcond_div_nm_info, '') AS biz_type,
            COALESCE(locplc_faclt_telno, '') AS phone
        FROM locallink.gg_restaurant_info
        WHERE MD5(bizplc_nm || COALESCE(refine_roadnm_addr,'')) = %s
        LIMIT 1
        """,
            (place_id,),
        )
    except Exception:
        _safe_rollback(cursor)
        return {"name": "이 식당", "region": "", "address": "", "category": "restaurant", "facts": []}

    place = cursor.fetchone()
    if not place:
        return {"name": "이 식당", "region": "", "address": "", "category": "restaurant", "facts": []}

    facts: list[str] = []
    for key in ("biz_type", "phone"):
        value = (place.get(key) or "").strip()
        if value:
            facts.append(value)

    return {
        "name": place["name"],
        "region": place["region"],
        "address": place["address"],
        "category": "restaurant",
        "facts": facts,
    }


def _load_event_context(cursor, place_id: str) -> dict[str, Any]:
    try:
        cursor.execute(
            f"""
        SELECT
            {_EVENT_ID_EXPR} AS id,
            COALESCE(title, '') AS name,
            COALESCE(city, '') AS region,
            COALESCE(inst_nm, '') AS address,
            COALESCE(begin_de, '') AS begin_de,
            COALESCE(end_de, '') AS end_de,
            COALESCE(url, '') AS event_url
        FROM locallink.gyeonggi_events
        WHERE {_EVENT_ID_EXPR} = %s
        LIMIT 1
        """,
            (place_id,),
        )
    except Exception:
        _safe_rollback(cursor)
        return {"name": "이 행사", "region": "", "address": "", "category": "event", "facts": []}

    place = cursor.fetchone()
    if not place:
        return {"name": "이 행사", "region": "", "address": "", "category": "event", "facts": []}

    facts: list[str] = []
    for key in ("begin_de", "end_de", "event_url"):
        value = (place.get(key) or "").strip()
        if value:
            facts.append(value)

    return {
        "name": place["name"],
        "region": place["region"],
        "address": place["address"],
        "category": "event",
        "facts": facts,
    }


def _generate_with_llm(context: dict[str, Any], category: str, language: str, mode: str) -> str:
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
    api_key = (os.getenv("AZURE_OPENAI_KEY") or "").strip()
    api_version = (os.getenv("AZURE_OPENAI_VERSION") or "").strip()
    deployment = (
        os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or ""
    ).strip()

    if not endpoint or not api_key or not api_version or not deployment:
        raise RuntimeError("azure openai config is missing")

    llm_timeout = max(3.0, min(_float_env("DOCENT_LLM_TIMEOUT_SEC", 6.0), 20.0))

    client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
        max_retries=0,
        timeout=llm_timeout,
    )

    language_name = "Korean" if language == "ko" else "English"
    sentence_rule = "3~4" if mode == "brief" else "6~8"

    facts = context.get("facts") or []
    facts_text = "\n".join(f"- {item}" for item in facts[:8])

    system_message = (
        "You are LALA docent writer for a location-based mobile app. "
        f"Write exactly {sentence_rule} conversational sentences in {language_name}. "
        "Mention practical tips and local context. Do not invent unavailable facts."
    )

    user_message = (
        f"Category: {category}\n"
        f"Name: {context.get('name', '')}\n"
        f"Region: {context.get('region', '')}\n"
        f"Address: {context.get('address', '')}\n"
        f"Known facts:\n{facts_text if facts_text else '- 없음'}"
    )

    response = client.chat.completions.create(
        model=deployment,
        temperature=0.5,
        max_tokens=320,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
    )

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("empty script")
    return content


def _fallback_script(context: dict[str, Any], category: str, language: str, mode: str) -> str:
    name = context.get("name") or ("이 장소" if language == "ko" else "this place")
    region = context.get("region") or ""
    address = context.get("address") or ""

    if language == "en":
        if mode == "detail":
            return (
                f"Welcome to {name}. This {category} is in {region}. "
                f"The address is {address}. Please check opening hours before visiting. "
                "Enjoy the area and follow local guidance signs."
            )
        return f"This is {name} in {region}. Check local conditions and opening hours before you visit."

    if mode == "detail":
        return (
            f"{name} 안내를 시작합니다. 이 장소는 {region}에 있습니다. "
            f"주소는 {address}입니다. 방문 전에 운영 시간과 현장 정보를 확인해 주세요. "
            "주변 보행 안전을 먼저 확인하고 이동해 주세요."
        )

    return f"{name}은(는) {region}에 있는 추천 장소입니다. 방문 전에 운영 시간과 현장 정보를 확인해 주세요."


def _cache_table_exists(cursor) -> bool:
    try:
        cursor.execute("SELECT to_regclass('locallink.docent_script_cache')")
        row = cursor.fetchone()
        return bool(row and row[0])
    except Exception:
        _safe_rollback(cursor)
        return False


def _safe_rollback(cursor) -> None:
    try:
        cursor.connection.rollback()
    except Exception:
        pass
