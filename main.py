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
        # [1] 구글 시트 연결
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).get_worksheet(0)

        # [2] API 세션 시작
        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        headers = {"User-Agent": "WikiSyncBot/1.0 (Contact: KimKingGe)"}

        # 로그인 프로세스
        res = session.get(API_URL, params={"action":"query","meta":"tokens","type":"login","format":"json"}).json()
        login_token = res['query']['tokens']['logintoken']
        
        login_res = session.post(API_URL, data={
            "action": "login",
            "lgname": WIKI_USER,
            "lgpassword": WIKI_PASS,
            "lgtoken": login_token,
            "format": "json"
        }).json()

        if login_res.get("login", {}).get("result") != "Success":
            raise Exception(f"위키 로그인 실패: {login_res}")

        all_rows = []
        apcontinue = ""
        max_parts = 1 
        
        # [수정] 무한 루프 방지 및 안정적인 네임스페이스 수집
        while True:
            # apnamespace를 '*' 대신 '0|10|14' 처럼 주요 번호를 직접 지정하는 것이 더 안전합니다.
            params = {
                "action": "query", 
                "list": "allpages", 
                "aplimit": "50", 
                "apnamespace": "0|10|14", # 일반(0), 틀(10), 분류(14)
                "format": "json", 
                "apcontinue": apcontinue
            }
            
            response = session.get(API_URL, params=params).json()
            
            if 'error' in response:
                raise Exception(f"API 에러 발생: {response['error']}")
                
            pages = response.get('query', {}).get('allpages', [])
            
            # 페이지를 못 가져왔을 때의 처리
            if not pages:
                print("더 이상 가져올 페이지가 없습니다.")
                break

            page_ids = [str(p['pageid']) for p in pages]

            prop_params = {
                "action": "query",
                "pageids": "|".join(page_ids),
                "prop": "revisions|categories|info",
                "rvprop": "user|content|timestamp|ids",
                "rvslots": "main",
                "format": "json"
            }
            prop_res = session.get(API_URL, params=prop_params).json()
            pages_detail = prop_res.get('query', {}).get('pages', {})

            for pid in page_ids:
                p_info = pages_detail.get(pid, {})
                if not p_info or 'title' not in p_info: continue
                
                title = p_info.get('title', 'N/A')
                ns = p_info.get('ns', 0)
                
                kind = "일반"
                if ns == 14: kind = "분류"
                elif ns == 10: kind = "틀"
                if "redirect" in p_info: kind += " (넘겨주기)"
                
                categories = p_info.get('categories', [])
                cat_names = ", ".join([c.get('title', '').replace('분류:', '') for c in categories])
                
                raw_json_str = json.dumps(p_info, indent=2, ensure_ascii=False)
                json_parts = split_json_data(raw_json_str, CELL_LIMIT)
                max_parts = max(max_parts, len(json_parts))
                
                all_rows.append([pid, title, kind, cat_names] + json_parts)

            if 'continue' in response:
                apcontinue = response['continue']['apcontinue']
                time.sleep(0.5) # 속도 조절
            else:
                break

        # [3] 시트 업데이트 (데이터가 있을 때만)
        if not all_rows:
            send_discord_bot_message("⚠️ 동기화 경고: 가져온 데이터가 0건입니다. 설정을 확인하세요.")
            return

        sheet.clear()
        header = ["페이지 ID", "문서 제목", "문서 종류", "분류"] + [f"JSON 데이터 {i+1}" for i in range(max_parts)]
        sheet.append_row(header)
        
        # 50행씩 안전하게 끊어서 입력
        for k in range(0, len(all_rows), 50):
            sheet.append_rows(all_rows[k:k+50])
            time.sleep(1)
        
        send_discord_bot_message(f"✅ **동기화 성공!**\n총 **{len(all_rows)}**개 문서 완료.")

    except Exception as e:
        print(f"에러 발생: {e}")
        send_discord_bot_message(f"❌ **동기화 실패**\n{str(e)}")

if __name__ == "__main__":
    run_sync()
