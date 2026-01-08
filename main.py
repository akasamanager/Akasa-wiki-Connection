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

CELL_LIMIT = 48000

def send_discord_bot_message(msg):
    if BOT_TOKEN and CHANNEL_ID:
        url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
        headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
        payload = {"content": msg}
        try: requests.post(url, headers=headers, json=payload)
        except: pass

def split_json_data(data_str, limit):
    return [data_str[i:i+limit] for i in range(0, len(data_str), limit)]

def run_sync():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).get_worksheet(0)

        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

        # 위키 로그인
        res = session.get(API_URL, params={"action":"query","meta":"tokens","type":"login","format":"json"}, headers=headers)
        login_token = res.json()['query']['tokens']['logintoken']
        session.post(API_URL, data={"action":"login","lgname":WIKI_USER,"lgpassword":WIKI_PASS,"lgtoken":login_token,"format":"json"}, headers=headers)

        all_rows = []
        apcontinue = ""
        max_parts = 1 
        
        while True:
            # [핵심 수정] apnamespace='*' 추가: 일반문서, 분류, 틀 등 모든 네임스페이스 포함
            params = {
                "action": "query", 
                "list": "allpages", 
                "aplimit": "50", 
                "apnamespace": "*", 
                "format": "json", 
                "apcontinue": apcontinue
            }
            res = session.get(API_URL, params=params, headers=headers).json()
            pages = res.get('query', {}).get('allpages', [])
            page_ids = [str(p['pageid']) for p in pages]
            if not page_ids: break

            # [보강] rvprop에 contentmodel 추가하여 표/템플릿 구조 파악 용이하게 함
            prop_params = {
                "action": "query",
                "pageids": "|".join(page_ids),
                "prop": "revisions|categories|info",
                "rvprop": "user|content|timestamp|ids|contentmodel",
                "rvslots": "main",
                "format": "json"
            }
            prop_res = session.get(API_URL, params=prop_params, headers=headers).json()
            pages_detail = prop_res.get('query', {}).get('pages', {})

            for pid in page_ids:
                p_info = pages_detail.get(pid, {})
                title = p_info.get('title', 'N/A')
                ns = p_info.get('ns', 0)
                
                # 문서 종류 판별 (네임스페이스 기반)
                kind = "일반"
                if ns == 14: kind = "분류"
                elif ns == 10: kind = "틀"
                
                if "redirect" in p_info:
                    kind += " (넘겨주기)"
                
                categories = p_info.get('categories', [])
                cat_names = ", ".join([c.get('title', '').replace('분류:', '') for c in categories])
                
                # JSON 데이터 생성 (표 템플릿 등 모든 revisions 데이터 포함)
                raw_json_str = json.dumps(p_info, indent=2, ensure_ascii=False)
                json_parts = split_json_data(raw_json_str, CELL_LIMIT)
                max_parts = max(max_parts, len(json_parts))
                
                row = [pid, title, kind, cat_names] + json_parts
                all_rows.append(row)

            if 'continue' in res:
                apcontinue = res['continue']['apcontinue']
                time.sleep(1)
            else: break

        sheet.clear()
        header = ["페이지 ID", "문서 제목", "문서 종류", "분류"] + [f"JSON 데이터 {i+1}" for i in range(max_parts)]
        sheet.append_row(header)
        
        if all_rows:
            # 데이터가 많을 경우를 대비해 100행씩 끊어서 입력 (안정성)
            for k in range(0, len(all_rows), 100):
                sheet.append_rows(all_rows[k:k+100])
        
        send_discord_bot_message(f"✅ **전체 네임스페이스 동기화 성공!**\n총 **{len(all_rows)}**개의 문서(분류/틀 포함)가 업데이트되었습니다.")

    except Exception as e:
        send_discord_bot_message(f"❌ **동기화 실패**\n{str(e)}")

if __name__ == "__main__":
    run_sync()
