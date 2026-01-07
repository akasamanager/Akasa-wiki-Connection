import os
import requests
import gspread
import json
import time
from oauth2client.service_account import ServiceAccountCredentials

# 1. 깃허브 Secrets에서 설정 로드
WIKI_USER = os.environ['WIKI_USER']
WIKI_PASS = os.environ['WIKI_PASS']
GOOGLE_JSON = os.environ['GOOGLE_CREDENTIALS']
BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
CHANNEL_ID = os.environ.get('DISCORD_CHANNEL_ID')
SHEET_ID = "1UUZEyqiSk8GBnhSyY-BYNZdc4uutIWD0ggO91oEbKEk"

def send_discord_bot_message(msg):
    """디스코드 봇 API를 통해 직접 메시지 전송"""
    if BOT_TOKEN and CHANNEL_ID:
        url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
        headers = {
            "Authorization": f"Bot {BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {"content": msg}
        try:
            res = requests.post(url, headers=headers, json=payload)
            res.raise_for_status()
        except Exception as e:
            print(f"디스코드 메시지 전송 실패: {e}")

def run_sync():
    try:
        # [단계 1] 구글 시트 인증 및 연결
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).get_worksheet(0)

        # [단계 2] 미라해제 위키 API 세션 시작
        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

        # 위키 로그인
        res = session.get(API_URL, params={"action":"query","meta":"tokens","type":"login","format":"json"}, headers=headers)
        login_token = res.json()['query']['tokens']['logintoken']
        session.post(API_URL, data={"action":"login","lgname":WIKI_USER,"lgpassword":WIKI_PASS,"lgtoken":login_token,"format":"json"}, headers=headers)

        # [단계 3] 위키 데이터 수집 (본문, 카테고리, 수정자 포함)
        all_data = []
        apcontinue = ""
        
        while True:
            params = {"action": "query", "list": "allpages", "aplimit": "20", "format": "json", "apcontinue": apcontinue}
            res = session.get(API_URL, params=params, headers=headers).json()
            pages = res.get('query', {}).get('allpages', [])
            page_ids = [str(p['pageid']) for p in pages]
            if not page_ids: break

            prop_params = {
                "action": "query", "pageids": "|".join(page_ids),
                "prop": "revisions|categories", "rvprop": "user|content", "rvslots": "main", "cllimit": "max", "format": "json"
            }
            prop_res = session.get(API_URL, params=prop_params, headers=headers).json()
            pages_detail = prop_res.get('query', {}).get('pages', {})

            for pid in page_ids:
                p_info = pages_detail.get(pid, {})
                title = p_info.get('title', 'N/A')
                last_user = p_info.get('revisions', [{}])[0].get('user', 'Unknown')
                content = p_info.get('revisions', [{}])[0].get('slots', {}).get('main', {}).get('*', '')
                content_preview = content[:500] + ("..." if len(content) > 500 else "")
                cats = [c['title'].replace('Category:', '') for c in p_info.get('categories', [])]
                cat_str = ", ".join(cats) if cats else "없음"
                all_data.append([pid, title, last_user, cat_str, content_preview])

            if 'continue' in res:
                apcontinue = res['continue']['apcontinue']
                time.sleep(1)
            else: break

        # [단계 4] 구글 시트 데이터 쓰기
        sheet.clear()
        sheet.append_row(["페이지 ID", "문서 제목", "최종 수정자", "카테고리", "본문 내용(요약)"])
        if all_data:
            sheet.append_rows(all_data)
        
        # [단계 5] 성공 알림 전송
        send_discord_bot_message(f"✅ **Akasa Universe 위키 동기화 완료!**\n총 **{len(all_data)}**개의 문서가 시트에 업데이트되었습니다.\n시트 확인하기: <https://docs.google.com/spreadsheets/d/{SHEET_ID}>")

    except Exception as e:
        send_discord_bot_message(f"❌ **위키 동기화 실패!**\n에러 내용: {str(e)}")

if __name__ == "__main__":
    run_sync()
