import requests
import xml.etree.ElementTree as ET
import pandas as pd

# 1. API 기본 세팅
api_url = "http://www.swcf.or.kr/openAPI/"
api_key = os.environ.get("SUWON_API_KEY")
cg_code = "29_EV"

params = {
    "CG": cg_code,
    "openAPIKey": api_key
}

# 2. API 호출
print("데이터를 불러오는 중입니다...")
response = requests.get(api_url, params=params)

if response.status_code == 200:
    # 3. XML 파싱
    root = ET.fromstring(response.content)
    events_list = []
    
    # <item> 태그 안의 세부 정보 추출
    for item in root.findall('.//item'):
        event_data = {
            "event_name": item.findtext('title') if item.find('title') is not None else "",
            "city": "수원시",
            "event_description": item.findtext('description') if item.find('description') is not None else "",
            "event_period": item.findtext('pubDate') if item.find('pubDate') is not None else "",
            "link": item.findtext('link') if item.find('link') is not None else ""
        }
        events_list.append(event_data)
        
    # 4. DataFrame 변환 및 CSV 저장 (한글 깨짐 방지 utf-8-sig)
    df = pd.DataFrame(events_list)
    csv_filename = "suwon_events_api_data.csv"
    df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
    
    print(f"🎉 성공! 총 {len(df)}건의 행사 데이터가 '{csv_filename}' 파일로 저장되었습니다.")
else:
    print(f"🚨 API 호출 실패! 상태 코드: {response.status_code}")
