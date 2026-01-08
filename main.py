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
        # [1] 구글 시트 연결
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).get_worksheet(0)

        # [2] 위키 API 연결 및 로그인 (충돌 방지 로직)
        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        session.headers.update({"User-Agent": "WikiDataSync/2.0"})

        # 1. Login Token 받기 (이 토큰은 로그인 전용입니다)
        res_t = session.get(API_URL, params={"action": "query", "meta": "tokens", "type": "login", "format": "json"}).json()
        l_token = res_t['query']['tokens']['logintoken']

        # 2. 로그인 실행
        login_payload = {
            "action": "login",
            "lgname": WIKI_USER,
            "lgpassword": WIKI_PASS,
            "lgtoken": l_token,
            "format": "json"
        }
        res_l = session.post(API_URL, data=login_payload).json()

        if res_l.get("login", {}).get("result") != "Success":
            send_discord_bot_message(f"❌ 로그인 단계 실패: {res_l}")
            return

        send_discord_bot_message("🔓 위키 인증 성공! 데이터 수집을 시작합니다.")

        # [3] 데이터 수집
        all_rows = []
        # 일반(0), 틀(10), 분류(14)
        target_namespaces = [0, 10, 14]
        
        for ns in target_namespaces:
            apcontinue = ""
            ns_name = "일반" if ns == 0 else ("틀" if ns == 10 else "분류")
            
            while True:
                # 데이터 읽기는 POST가 아닌 GET으로 안전하게 요청
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

                # 상세 데이터 (Revision) 가져오기
                pids = [str(p['pageid']) for p in pages]
                p_params = {
                    "action": "query",
                    "pageids": "|".join(pids),
                    "prop": "revisions|categories|info",
                    "rvprop": "content",
                    "rvslots": "main",
                    "format": "json"
                }
                res_p = session.get(API_URL, params=p_params).json()
                pages_detail = res_p.get('query', {}).get('pages', {})

                for pid in pids:
                    p_info = pages_detail.get(pid, {})
                    title = p_info.get('title', 'N/A')
                    
                    kind = ns_name
                    if "redirect" in p_info: kind += " (넘겨주기)"

                    # 분류 정보
                    cats = p_info.get('categories', [])
                    cat_names = ", ".join([c.get('title', '').replace('분류:', '') for c in cats])

                    # JSON 데이터 분할
                    raw_json = json.dumps(p_info, ensure_ascii=False)
                    json_parts = [raw_json[i:i+45000] for i in range(0, len(raw_json), 45000)]
                    
                    all_rows.append([pid, title, kind, cat_names] + json_parts)

                if 'continue' in res:
                    apcontinue = res['continue']['apcontinue']
                    time.sleep(0.3)
                else:
                    break
            
            send_discord_bot_message(f"📊 {ns_name} 네임스페이스 수집 완료 ({len(all_rows)}행 누적)")

        # [4] 시트 업데이트
        if all_rows:
            sheet.clear()
            max_col = max(len(r) for r in all_rows)
            header = ["ID", "제목", "종류", "분류"] + [f"JSON_{i}" for i in range(1, max_col - 3)]
            sheet.append_row(header)
            
            for i in range(0, len(all_rows), 50):
                sheet.append_rows(all_rows[i:i+50])
            
            send_discord_bot_message(f"✅ 동기화 완료! 총 {len(all_rows)}개의 문서를 저장했습니다.")
        else:
            send_discord_bot_message("⚠️ 수집된 데이터가 최종적으로 0건입니다.")

    except Exception as e:
        send_discord_bot_message(f"🔥 에러 상세내용: {str(e)}")

if __name__ == "__main__":
    run_sync()
