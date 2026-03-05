import pandas as pd
import os

# 1. 파일 경로 설정 (지정해준 절대 경로 사용)
path_old = r"C:\Users\EL058\Documents\1st-project\3dt-1st-Project\data\event_info_preprocessed.csv"
path_new = r"C:\Users\EL058\Documents\1st-project\3dt-1st-Project\data\gyeonggi-cultural-foundation-events.csv"
output_dir = r"C:\Users\EL058\Documents\1st-project\3dt-1st-Project\data\processed"
output_file = os.path.join(output_dir, "gyeonggi_events_final.csv")

# 저장할 폴더가 없으면 자동 생성
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

print("데이터 불러오는 중...")
# 2. 기존 전처리 데이터 불러오기
df_old = pd.read_csv(path_old, encoding='utf-8')

# 3. 신규 경기문화재단 데이터 불러오기 (인코딩 에러 방지)
try:
    df_new = pd.read_csv(path_new, encoding='utf-8')
except UnicodeDecodeError:
    df_new = pd.read_csv(path_new, encoding='euc-kr')

# 4. 신규 데이터 컬럼을 기존 DB 규격(영어)에 맞게 맵핑 및 추출
df_new_mapped = pd.DataFrame()
df_new_mapped['inst_nm'] = df_new['주최주관']
df_new_mapped['title'] = df_new['제목']
df_new_mapped['url'] = df_new['출처 url']
df_new_mapped['image_url'] = df_new['og image']

# [필수 조건 1 & 2] 행사 시작일 / 종료일 (시간 제거하고 YYYY-MM-DD 형태만 추출)
df_new_mapped['begin_de'] = df_new['시작일'].astype(str).str.split(' ').str[0]
df_new_mapped['end_de'] = df_new['종료일'].astype(str).str.split(' ').str[0]
df_new_mapped['writng_de'] = df_new['시작일'].astype(str).str.split(' ').str[0]

# [필수 조건 3] 행사 위치 (용인, 수원 철저하게 추출)
def extract_city(loc):
    loc = str(loc)
    
    # 용인/수원은 구 이름만 있어도 잡아내도록 특별 처리
    if '수원' in loc or any(gu in loc for gu in ['팔달', '영통', '장안', '권선']):
        return '수원시'
    if '용인' in loc or any(gu in loc for gu in ['기흥', '수지', '처인']):
        return '용인시'
        
    # 나머지 경기도 시/군 처리
    cities = ['성남', '고양', '부천', '화성', '평택', '남양주', '파주', '의정부', '광주', '양평', '연천', '가평', '안양', '안산', '과천', '광명', '군포', '김포', '동두천', '시흥', '안성', '오산', '의왕', '이천', '하남']
    for city in cities:
        if city in loc:
            return city + ('군' if city in ['양평', '연천', '가평'] else '시')
    
    # 시/군 정보를 도저히 찾을 수 없을 때
    return '기타'

df_new_mapped['city'] = df_new['위치'].apply(extract_city)

print("데이터 병합 및 정제 중...")
# 5. 두 데이터 위아래로 병합
df_merged = pd.concat([df_old, df_new_mapped], ignore_index=True)

# 6. URL 기준으로 중복 행사 제거
initial_count = len(df_merged)
df_merged = df_merged.drop_duplicates(subset=['url'])
final_count = len(df_merged)
print(f"중복 데이터 {initial_count - final_count}건 제거 완료!")

# 7. 결측치(NaN) 처리 및 최종 저장
df_merged = df_merged.fillna('')
df_merged.to_csv(output_file, index=False, encoding='utf-8-sig')

print(f"🎉 성공! 최종 파일이 지정된 경로에 생성되었습니다.")
print(f"저장 위치: {output_file} (총 {final_count}건)")