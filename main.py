import os
import requests
import gspread
import json
import time
from oauth2client.service_account import ServiceAccountCredentials

# 설정 로드
WIKI_USER = os.environ['WIKI_USER']
WIKI_PASS = os.environ['WIKI_PASS']
GOOGLE_JSON = os.environ['GOOGLE_CREDENTIALS']
BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
CHANNEL_ID = os.environ.get('DISCORD_CHANNEL_ID')
SHEET_ID = "1UUZEyqiSk8GBnhSyY-BYNZdc4uutIWD0ggO91oEbKEk"

# 구글 시트 셀 제한 (안전하게 48,000자로 설정)
CELL_LIMIT = 48000

def send_discord_bot_message(msg):
    if BOT_TOKEN and CHANNEL_ID:
        url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
        headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
        payload = {"content": msg}
        try: requests.post(url, headers=headers, json=payload)
        except: pass

def split_json_data(data_str, limit):
    """데이터를 제한 길이에 맞춰 리스트로 분할"""
    return [data_str[i:i+limit] for i in range(0, len(data_str), limit)]

def run_sync():
    try:
        # [1] 구글 시트 인증
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).get_worksheet(0)

        # [2] 미라해제 API 세션
        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

        # 위키 로그인
        res = session.get(API_URL, params={"action":"query","meta":"tokens","type":"login","format":"json"}, headers=headers)
        login_token = res.json()['query']['tokens']['logintoken']
        session.post(API_URL, data={"action":"login","lgname":WIKI_USER,"lgpassword":WIKI_PASS,"lgtoken":login_token,"format":"json"}, headers=headers)

        all_rows = []
        apcontinue = ""
        max_parts = 1 # 헤더 생성을 위해 최대 분할 수 추적
        
        while True:
            params = {"action": "query", "list": "allpages", "aplimit": "20", "format": "json", "apcontinue": apcontinue}
            res = session.get(API_URL, params=params, headers=headers).json()
            pages = res.get('query', {}).get('allpages', [])
            page_ids = [str(p['pageid']) for p in pages]
            if not page_ids: break

            prop_params = {
                "action": "query",
                "pageids": "|".join(page_ids),
                "prop": "revisions|categories|info",
                "rvprop": "user|content|timestamp|ids",
                "rvslots": "main",
                "format": "json"
            }
            prop_res = session.get(API_URL, params=prop_params, headers=headers).json()
            pages_detail = prop_res.get('query', {}).get('pages', {})

            for pid in page_ids:
                p_info = pages_detail.get(pid, {})
                title = p_info.get('title', 'N/A')
                
                # JSON 문자열 변환
                raw_json_str = json.dumps(p_info, indent=2, ensure_ascii=False)
                
                # [핵심] 데이터 분할 실행
                json_parts = split_json_data(raw_json_str, CELL_LIMIT)
                max_parts = max(max_parts, len(json_parts))
                
                # 한 줄 데이터 구성: [ID, 제목, JSON_파트1, JSON_파트2, ...]
                row = [pid, title] + json_parts
                all_rows.append(row)

            if 'continue' in res:
                apcontinue = res['continue']['apcontinue']
                time.sleep(1)
            else: break

        # [3] 시트 업데이트
        sheet.clear()
        
        # 동적으로 헤더 생성 (JSON 데이터 1, JSON 데이터 2...)
        header = ["페이지 ID", "문서 제목"] + [f"JSON 데이터 {i+1}" for i in range(max_parts)]
        sheet.append_row(header)
        
        if all_rows:
            sheet.append_rows(all_rows)
        
        send_discord_bot_message(f"✅ **셀 분할 동기화 성공!**\n총 **{len(all_rows)}**개의 문서가 업데이트되었습니다.\n(최대 분할 수: {max_parts})")

    except Exception as e:
        send_discord_bot_message(f"❌ **동기화 실패**\n{str(e)}")

if __name__ == "__main__":
    run_sync()
