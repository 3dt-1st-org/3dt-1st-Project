import pandas as pd
import psycopg2
from psycopg2.extras import execute_values  # 성능 최적화를 위해 추가
from pathlib import Path
import os
from dotenv import load_dotenv

# 환경 및 설정 (기존 코드 유지)
load_dotenv()
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'postgres'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD'),
    'port': int(os.getenv('DB_PORT', 5432))
}

# 컬럼 매핑 (데이터 출처 추가)
COLUMN_MAPPING = {
    '사업장명': 'bizplc_nm',
    '소재지도로명주소': 'refine_roadnm_addr',
    '소재지지번주소': 'refine_lotno_addr',
    '위도': 'refine_wgs84_lat',
    '경도': 'refine_wgs84_logt',
    '통합영업상태명': 'unity_bsn_state_nm',
    '영업상태명': 'bsn_state_nm',
    '휴업시작일자': 'suspnbiz_begin_de',
    '휴업종료일자': 'suspnbiz_end_de',
    '재개업일자': 'reopenbiz_de',
    '소재지시설전화번호': 'locplc_faclt_telno',
    '업태구분명정보': 'bizcond_div_nm_info',
    'X좌표값': 'x_crdnt_vl',
    'Y좌표값': 'y_crdnt_vl',
    '위생업태명': 'sanittn_bizcond_nm',
    '시군명': 'sigun_nm',
}

def read_csv_files():
    """3개의 CSV 파일을 읽어서 하나로 합침"""
    print("\n[1/3] Loading CSV files from data/raw...")
    
    base_path = Path(__file__).parent.parent.parent / 'data' / 'raw'
    files = [
        '일반음식점현황_인허가_수원.csv',
        '일반음식점현황_인허가_용인.csv',
        '일반음식점현황_인허가_평택.csv'
    ]
    
    dfs = []
    expected_cols = set(COLUMN_MAPPING.keys())
    encodings = ['cp949', 'euc-kr', 'utf-8-sig', 'utf-8']
    
    for file in files:
        file_path = base_path / file
        print(f"  - Reading {file}...")
        
        df = None
        for encoding in encodings:
            try:
                candidate = pd.read_csv(file_path, encoding=encoding, low_memory=False)
                matched = expected_cols.intersection(candidate.columns)
                print(f"    Tried {encoding}: matched {len(matched)}/{len(expected_cols)} columns")
                if len(matched) >= len(expected_cols) - 2:
                    df = candidate
                    print(f"    Loaded {len(df)} rows (encoding: {encoding})")
                    break
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        if df is None:
            raise ValueError(f"Failed to read {file} with expected columns using {encodings}")
        
        # 첫 파일의 컬럼명 출력 (디버깅용)
        if len(dfs) == 0:
            print(f"\n    실제 CSV 컬럼명 (처음 16개):")
            for i, col in enumerate(df.columns[:16], 1):
                print(f"      [{i}] {col}")
        
        dfs.append(df)
    
    # 3개 파일 병합
    combined_df = pd.concat(dfs, ignore_index=True)
    print(f"\n  Total: {len(combined_df)} rows combined")
    
    # 선택된 컬럼만 추출
    selected_columns = list(COLUMN_MAPPING.keys())
    combined_df = combined_df[selected_columns]
    
    return combined_df

def clean_data(df):
    print("\n[2/3] Cleaning data...")
    
    # 먼저 컬럼명 변경
    df = df.rename(columns=COLUMN_MAPPING)
    
    # 1. 문자열 결측치를 먼저 None으로 처리
    str_cols = ['bizplc_nm', 'refine_roadnm_addr', 'refine_lotno_addr', 
                'unity_bsn_state_nm', 'bsn_state_nm', 'locplc_faclt_telno',
                'bizcond_div_nm_info', 'sanittn_bizcond_nm', 'sigun_nm']
    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].where(pd.notna(df[col]), None)
    
    # 2. 날짜 처리: NaT를 None으로 변환
    date_cols = ['suspnbiz_begin_de', 'suspnbiz_end_de', 'reopenbiz_de']
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
            df[col] = df[col].apply(lambda x: x.date() if pd.notna(x) else None)
            
    # 3. 숫자 처리: 콤마 제거 및 타입 변환
    num_cols = ['refine_wgs84_lat', 'refine_wgs84_logt', 'x_crdnt_vl', 'y_crdnt_vl']
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')
            df[col] = df[col].apply(lambda x: None if pd.isna(x) else x)
    
    # 디버깅: 첫 3개 행 출력
    print("\n샘플 데이터 (첫 3행):")
    print(df.head(3).to_string())
    
    return df

def insert_data(conn, df):
    print(f"\n[3/3] Inserting {len(df)} rows using execute_values...")
    columns = list(df.columns)
    query = f"INSERT INTO locallink.gg_restaurant_info ({','.join(columns)}) VALUES %s"
    
    # 데이터를 튜플 리스트로 변환
    data_values = [tuple(x) for x in df.values]
    
    with conn.cursor() as cur:
        # execute_values를 사용한 고속 배치 삽입
        execute_values(cur, query, data_values, page_size=1000)
    conn.commit()
    print("Insertion completed.")

def main():
    conn = None
    try:
        # 1. Load - 3개 CSV 파일 읽어서 합치기
        df = read_csv_files() 
        
        # 2. Clean - 데이터 정제 및 컬럼명 변경
        df = clean_data(df)
        
        # 3. Connect - DB 연결
        conn = psycopg2.connect(**DB_CONFIG)
        
        # 4. Insert - 데이터 삽입
        insert_data(conn, df)
        
        print("\n[Success] ETL Process finished successfully.")
        
    except Exception as e:
        print(f"\n[Error] {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    main()