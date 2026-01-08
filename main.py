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

def send_discord_bot_message(msg):
    if BOT_TOKEN and CHANNEL_ID:
        url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
        headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
        payload = {"content": msg}
        try: requests.post(url, headers=headers, json=payload)
        except: pass

def safe_api_call(session, url, params=None, data=None, method="GET"):
    """서버 응답이 JSON이 아닐 경우를 대비한 안전한 호출 함수"""
    try:
        if method == "GET":
            res = session.get(url, params=params, timeout=30)
        else:
            res = session.post(url, data=data, timeout=30)
        
        # 서버가 에러 코드를 보냈는지 확인
        res.raise_for_status()
        return res.json()
    except Exception as e:
        # 에러 발생 시 서버가 보낸 실제 텍스트 내용을 로그로 남김
        print(f"API 호출 에러: {str(e)}")
        return None

def run_sync():
    try:
        # [1] 구글 시트 연결
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).get_worksheet(0)

        # [2] 위키 세션 및 로그인 (헤더 보강)
        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        # 로그인 1단계
        t_res = safe_api_call(session, API_URL, params={"action":"query","meta":"tokens","type":"login","format":"json"})
        if not t_res: raise Exception("서버에서 로그인 토큰을 가져오지 못했습니다.")
        
        l_token = t_res['query']['tokens']['logintoken']
        
        # 로그인 2단계
        l_res = safe_api_call(session, API_URL, method="POST", data={
            "action": "login", "lgname": WIKI_USER, "lgpassword": WIKI_PASS, "lgtoken": l_token, "format": "json"
        })
        
        if not l_res or l_res.get("login", {}).get("result") != "Success":
            send_discord_bot_message(f"❌ 위키 로그인 실패: {l_res}")
            return

        send_discord_bot_message("✅ 로그인 성공, 데이터 수집을 시작합니다.")

        # [3] 데이터 수집
        all_rows = []
        namespaces = ["0", "10", "14"]
        
        for ns in namespaces:
            apcontinue = ""
            while True:
                params = {
                    "action": "query", "list": "allpages", "apnamespace": ns,
                    "aplimit": "50", "format": "json", "apcontinue": apcontinue
                }
                res = safe_api_call(session, API_URL, params=params)
                if not res: break
                
                pages = res.get('query', {}).get('allpages', [])
                if not pages: break
                
                page_ids = [str(p['pageid']) for p in pages]
                
                # 상세 데이터
                p_params = {
                    "action": "query", "pageids": "|".join(page_ids),
                    "prop": "revisions|categories|info", "rvprop": "content",
                    "rvslots": "main", "format": "json"
                }
                p_res = safe_api_call(session, API_URL, params=p_params)
                if not p_res: continue
                
                pages_data = p_res.get('query', {}).get('pages', {})
                
                for pid in page_ids:
                    p_info = pages_data.get(pid, {})
                    title = p_info.get('title', 'N/A')
                    kind = "일반" if ns == "0" else ("틀" if ns == "10" else "분류")
                    
                    raw_json = json.dumps(p_info, ensure_ascii=False)
                    parts = [raw_json[i:i+45000] for i in range(0, len(raw_json), 45000)]
                    all_rows.append([pid, title, kind, ""] + parts)
                
                if 'continue' in res:
                    apcontinue = res['continue']['apcontinue']
                else:
                    break

        # [4] 시트 업데이트
        if all_rows:
            sheet.clear()
            max_col = max(len(r) for r in all_rows)
            header = ["ID", "제목", "종류", "분류"] + [f"JSON_{i}" for i in range(1, max_col - 3)]
            sheet.append_row(header)
            
            for i in range(0, len(all_rows), 50):
                sheet.append_rows(all_rows[i:i+50])
            
            send_discord_bot_message(f"✅ 총 {len(all_rows)}건 업데이트 완료! (분류/틀 포함)")
        else:
            send_discord_bot_message("⚠️ 수집된 데이터가 없습니다.")

    except Exception as e:
        send_discord_bot_message(f"🔥 에러 발생: {str(e)}")

if __name__ == "__main__":
    run_sync()
