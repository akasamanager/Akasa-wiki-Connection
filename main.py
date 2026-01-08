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

def run_sync():
    try:
        # [1] 구글 시트 초기 연결 확인
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).get_worksheet(0)
        send_discord_bot_message("🔍 시스템 시작: 구글 시트 연결 성공")

        # [2] 위키 세션 및 로그인
        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        
        # 로그인 1단계: 토큰 받기
        t_res = session.get(API_URL, params={"action":"query","meta":"tokens","type":"login","format":"json"}).json()
        l_token = t_res['query']['tokens']['logintoken']
        
        # 로그인 2단계: 실제 로그인
        l_res = session.post(API_URL, data={"action":"login","lgname":WIKI_USER,"lgpassword":WIKI_PASS,"lgtoken":l_token,"format":"json"}).json()
        
        if l_res.get("login", {}).get("result") != "Success":
            send_discord_bot_message(f"❌ 로그인 실패: {l_res}")
            return

        # [3] 데이터 수집 (가장 안전한 방식으로 변경)
        all_rows = []
        # 네임스페이스를 하나씩 따로 시도하거나, 혹은 지정을 아예 빼버리고 기본값부터 확인
        namespaces = ["0", "10", "14"] # 일반, 틀, 분류
        
        for ns in namespaces:
            apcontinue = ""
            ns_count = 0
            while True:
                params = {
                    "action": "query",
                    "list": "allpages",
                    "apnamespace": ns,
                    "aplimit": "50",
                    "format": "json",
                    "apcontinue": apcontinue
                }
                res = session.get(API_URL, params=params).json()
                pages = res.get('query', {}).get('allpages', [])
                
                if not pages:
                    break
                
                page_ids = [str(p['pageid']) for p in pages]
                
                # 상세 데이터 가져오기
                p_params = {
                    "action": "query",
                    "pageids": "|".join(page_ids),
                    "prop": "revisions|categories|info",
                    "rvprop": "content",
                    "rvslots": "main",
                    "format": "json"
                }
                p_res = session.get(API_URL, params=p_params).json()
                pages_data = p_res.get('query', {}).get('pages', {})
                
                for pid in page_ids:
                    p_info = pages_data.get(pid, {})
                    title = p_info.get('title', 'N/A')
                    kind = "일반" if ns == "0" else ("틀" if ns == "10" else "분류")
                    
                    raw_json = json.dumps(p_info, ensure_ascii=False)
                    # 데이터 분할 (45000자 기준)
                    parts = [raw_json[i:i+45000] for i in range(0, len(raw_json), 45000)]
                    
                    all_rows.append([pid, title, kind, ""] + parts)
                    ns_count += 1
                
                if 'continue' in res:
                    apcontinue = res['continue']['apcontinue']
                else:
                    break
            send_discord_bot_message(f"📊 네임스페이스 {ns} 수집 완료: {ns_count}건")

        # [4] 시트 업데이트
        if all_rows:
            sheet.clear()
            # 헤더는 데이터 구조에 맞춰 유동적으로 생성
            max_col = max(len(r) for r in all_rows)
            header = ["ID", "제목", "종류", "분류"] + [f"JSON_{i}" for i in range(1, max_col - 3)]
            sheet.append_row(header)
            
            # 50개씩 끊어서 입력
            for i in range(0, len(all_rows), 50):
                sheet.append_rows(all_rows[i:i+50])
            
            send_discord_bot_message(f"✅ 총 {len(all_rows)}건 업데이트 완료!")
        else:
            send_discord_bot_message("⚠️ 수집된 데이터가 최종적으로 0건입니다.")

    except Exception as e:
        send_discord_bot_message(f"🔥 치명적 에러: {str(e)}")

if __name__ == "__main__":
    run_sync()
