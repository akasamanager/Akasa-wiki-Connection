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
        # 첫 번째 시트(DataLaw로 사용 중인 시트)를 엽니다.
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
        max_parts = 1 
        
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
                
                # [수정] C열: 문서 종류 (넘겨주기 여부 확인)
                is_redirect = "넘겨주기" if "redirect" in p_info else "일반 문서"
                
                # [수정] D열: 분류 추출
                categories = p_info.get('categories', [])
                cat_names = ", ".join([c.get('title', '').replace('분류:', '') for c in categories])
                
                # JSON 문자열 변환
                raw_json_str = json.dumps(p_info, indent=2, ensure_ascii=False)
                
                # 데이터 분할
                json_parts = split_json_data(raw_json_str, CELL_LIMIT)
                max_parts = max(max_parts, len(json_parts))
                
                # [수정] 한 줄 데이터 구성: [ID, 제목, 종류, 분류, JSON_파트1, ...]
                row = [pid, title, is_redirect, cat_names] + json_parts
                all_rows.append(row)

            if 'continue' in res:
                apcontinue = res['continue']['apcontinue']
                time.sleep(1)
            else: break

        # [3] 시트 업데이트
        sheet.clear()
        
        # [수정] 헤더 생성 (C, D열 추가 반영)
        header = ["페이지 ID", "문서 제목", "문서 종류", "분류"] + [f"JSON 데이터 {i+1}" for i in range(max_parts)]
        sheet.append_row(header)
        
        if all_rows:
            sheet.append_rows(all_rows)
        
        send_discord_bot_message(f"✅ **동기화 성공! (분류/종류 추가)**\n총 **{len(all_rows)}**개의 문서가 업데이트되었습니다.")

    except Exception as e:
        send_discord_bot_message(f"❌ **동기화 실패**\n{str(e)}")

if __name__ == "__main__":
    run_sync()
