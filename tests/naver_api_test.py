import urllib.request
import urllib.parse
import json
import os
import dotenv

dotenv.load_dotenv()

# 1. 키 및 검색어 설정
client_id = os.getenv("NAVER_CLIENT_ID")
client_secret = os.getenv("NAVER_CLIENT_SECRET")

if not client_id or not client_secret:
    raise ValueError("환경변수 NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 설정되지 않았습니다.")

search_word = urllib.parse.quote("경복궁 리뷰")

# 2. API 요청 및 결과 수신 (최대 100개, 유사도순)
url = f"https://openapi.naver.com/v1/search/blog?query={search_word}&display=10&sort=sim"
request = urllib.request.Request(url)
request.add_header("X-Naver-Client-Id", client_id)
request.add_header("X-Naver-Client-Secret", client_secret)

response = urllib.request.urlopen(request)
if response.getcode() == 200:
    data = json.loads(response.read().decode('utf-8'))
    # 3. 결과 출력 (제목, 링크, 요약)
    for item in data['items']:
        print(f"제목: {item['title']}\n링크: {item['link']}\n")
else:
    print("Error Code:", response.getcode())