import os
import requests
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials

# 1. 환경 변수에서 설정 로드
WIKI_USER = os.environ['WIKI_USER']
WIKI_PASS = os.environ['WIKI_PASS']
GOOGLE_JSON = os.environ['GOOGLE_CREDENTIALS']
SHEET_ID = "1UUZEyqiSk8GBnhSyY-BYNZdc4uutIWD0ggO91oEbKEk"

def run_sync():
    # [구글 시트 인증]
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_JSON)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).get_worksheet(0) # 첫 번째 시트

    # [미라해제 로그인 및 데이터 수집]
    API_URL = "https://akasauniverse.miraheze.org/w/api.php"
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

    # 로그인 토큰 받기
    res = session.get(API_URL, params={"action": "query", "meta": "tokens", "type": "login", "format": "json"}, headers=headers)
    login_token = res.json()['query']['tokens']['logintoken']

    # 로그인 실행
    session.post(API_URL, data={"action": "login", "lgname": WIKI_USER, "lgpassword": WIKI_PASS, "lgtoken": login_token, "format": "json"}, headers=headers)

    # 모든 문서 가져오기
    all_pages = []
    last_continue = {}
    while True:
        params = {"action": "query", "list": "allpages", "aplimit": "max", "format": "json"}
        params.update(last_continue)
        res = session.get(API_URL, params=params, headers=headers)
        data = res.json()
        if 'query' in data:
            for page in data['query']['allpages']:
                all_pages.append([page['pageid'], page['title']])
        if 'continue' in data: last_continue = data['continue']
        else: break

    # [시트에 업데이트]
    sheet.clear()
    sheet.append_row(["페이지 ID", "문서 제목"])
    if all_pages:
        sheet.append_rows(all_pages)
    print(f"성공: {len(all_pages)}개 업데이트 완료!")

if __name__ == "__main__":
    run_sync()
