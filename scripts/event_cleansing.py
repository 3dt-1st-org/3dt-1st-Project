import os
import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import find_dotenv, load_dotenv
from openai import OpenAI
from tqdm import tqdm

GYEONGGI_CITIES = [
    "수원시", "성남시", "의정부시", "안양시", "부천시", "광명시", "평택시", "동두천시",
    "안산시", "고양시", "과천시", "구리시", "남양주시", "오산시", "시흥시", "군포시",
    "의왕시", "하남시", "용인시", "파주시", "이천시", "안성시", "김포시", "화성시",
    "광주시", "양주시", "포천시", "여주시", "연천군", "가평군", "양평군",
]

CITY_ALIASES: dict[str, str] = {}
for city in GYEONGGI_CITIES:
    CITY_ALIASES[city] = city
    CITY_ALIASES[city.replace("시", "").replace("군", "")] = city


def resolve_input_path() -> Path:
    candidates = [
        Path("data/raw/event_info_202602261456.csv"),
        Path("data/event_info_202602261456.csv"),
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "입력 CSV를 찾을 수 없습니다. 확인한 경로: "
        + ", ".join(str(p) for p in candidates)
    )


def parse_date_from_text(text: str, key: str) -> str | None:
    pattern = rf"{key}\s*[:：]\s*(\d{{4}}-\d{{2}}-\d{{2}})"
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None


def extract_city_from_text(text: str) -> str | None:
    if not text:
        return None
    # 긴 지명(예: 남양주) 우선 매칭
    for key in sorted(CITY_ALIASES.keys(), key=len, reverse=True):
        if key and key in text:
            return CITY_ALIASES[key]
    return None


def fetch_page_text(session: requests.Session, url: str) -> str:
    response = session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return soup.get_text(separator=" ", strip=True)[:4000]


def get_city_from_url(
    session: requests.Session,
    title: str,
    url: str,
    cache: dict[str, str],
) -> str:
    # 1) 제목/URL 문자열에서 우선 추출
    direct_city = extract_city_from_text(f"{title} {url}")
    if direct_city:
        return direct_city

    # 2) URL 페이지 본문에서 추출
    if pd.isna(url) or not isinstance(url, str) or not url.strip():
        return "기타"
    if url in cache:
        return cache[url]

    try:
        page_text = fetch_page_text(session, url)
        city = extract_city_from_text(page_text) or "기타"
        cache[url] = city
        return city
    except Exception:
        cache[url] = "기타"
        return "기타"


def extract_dates(client: OpenAI, url: str, title: str) -> str:
    if pd.isna(url):
        return "오류"
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        page_text = soup.get_text(separator=" ", strip=True)[:1500]

        prompt = (
            f"행사명: {title}\n"
            f"내용: {page_text}\n"
            "이게 관광객 행사면 시작일과 종료일(YYYY-MM-DD)을 알려줘. "
            "아니면 '관광객행사: X'라고 해줘. "
            "양식: [관광객행사: O, 시작일: 0000-00-00, 종료일: 0000-00-00]"
        )
        ans = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=80,
        )
        return (ans.choices[0].message.content or "").strip() or "오류"
    except Exception:
        return "오류"


def main() -> None:
    load_dotenv(find_dotenv())
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY가 .env에 설정되어 있어야 합니다.")
    client = OpenAI(api_key=api_key)

    input_path = resolve_input_path()
    
    # 결과 저장 폴더 설정
    output_dir = Path("data/processed") # 팀 폴더 구조에 맞춰 processed로 수정 추천
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "event_info_preprocessed.csv"

    print("데이터 전처리를 시작합니다...")
    print(f"입력 파일: {input_path}")
    df = pd.read_csv(input_path, encoding="utf-8-sig")

    if "title" not in df.columns:
        raise KeyError("'title' 컬럼이 필요합니다.")
    if "url" not in df.columns:
        raise KeyError("'url' 컬럼이 필요합니다.")
    if "begin_de" not in df.columns:
        df["begin_de"] = pd.NA
    if "end_de" not in df.columns:
        df["end_de"] = pd.NA

    # 1. 기존 컬럼 삭제
    df = df.drop(columns=["category_nm", "city"], errors="ignore")
    print("1단계: 기존 category_nm, city 컬럼 삭제 완료")

    # 2. city 재생성 (URL/본문 기반)
    print("2단계: URL 기반으로 'city' 컬럼 재생성 시작...")
    tqdm.pandas()
    session = requests.Session()
    city_cache: dict[str, str] = {}
    df["city"] = df.progress_apply(
        lambda row: get_city_from_url(session, row["title"], row["url"], city_cache),
        axis=1,
    )

    # 3. 단순 공지 제거 + 날짜 결측치 복구
    drop_keywords = ["취임", "임용", "선정"]
    mask_missing_dates = df["begin_de"].isna() | df["end_de"].isna()
    mask_to_drop = mask_missing_dates & df["title"].str.contains(
        "|".join(drop_keywords),
        na=False,
    )

    df = df[~mask_to_drop].copy()

    print("3단계: 날짜 결측치 URL 스크래핑 및 복구 시작...")
    mask_still_missing = df["begin_de"].isna() | df["end_de"].isna()
    missing_rows = df[mask_still_missing]

    for idx, row in tqdm(missing_rows.iterrows(), total=len(missing_rows)):
        time.sleep(0.5)
        result = extract_dates(client, row["url"], row["title"])

        if "관광객행사: O" in result:
            begin_val = parse_date_from_text(result, "시작일")
            end_val = parse_date_from_text(result, "종료일")
            if begin_val and end_val:
                df.at[idx, "begin_de"] = begin_val
                df.at[idx, "end_de"] = end_val
            else:
                df.at[idx, "begin_de"] = "삭제대상"
        elif "관광객행사: X" in result or result == "오류":
            df.at[idx, "begin_de"] = "삭제대상"

    df = df[df["begin_de"] != "삭제대상"].copy()

    # =================================================================
    # 🔥 4단계: 군포시 환각(Hallucination) 오류 보정 로직 
    # =================================================================
    print(f"보정 전 '군포시' 개수: {len(df[df['city'] == '군포시'])}건")

    yongin_keywords = ['경기도박물관', '한국민속촌', '경기도어린이박물관', '백남준아트센터', '용인', '처인성', '상상의숲', '농촌테마파크']
    suwon_keywords = ['수원', '경기상상캠퍼스', '경기도사이버도서관', '경기문화재단']

    def fix_city(row):
        if row['city'] == '군포시':
            title = str(row['title'])
            if any(kw in title for kw in yongin_keywords): return '용인시'
            elif any(kw in title for kw in suwon_keywords): return '수원시'
            else: return '기타'
        return row['city']

    df['city'] = df.apply(fix_city, axis=1)
    print(f"보정 후 '군포시' 개수: {len(df[df['city'] == '군포시'])}건")
    # =================================================================

    # 최종 결과를 CSV로 저장
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"🎉 모든 전처리 완료! [{output_path}] 생성됨.")


if __name__ == "__main__":
    main()