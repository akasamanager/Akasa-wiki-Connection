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

        # [2] 위키 API 연결 및 로그인
        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        session.headers.update({"User-Agent": "WikiDataSync_ImageEmbedded/2.2"})

        res_t = session.get(API_URL, params={"action": "query", "meta": "tokens", "type": "login", "format": "json"}).json()
        l_token = res_t['query']['tokens']['logintoken']
        session.post(API_URL, data={"action": "login", "lgname": WIKI_USER, "lgpassword": WIKI_PASS, "lgtoken": l_token, "format": "json"})

        send_discord_bot_message("📦 JSON 내부에 이미지 URL을 포함하여 동기화합니다.")

        all_rows = []
        target_namespaces = [0, 10, 14]
        
        for ns in target_namespaces:
            apcontinue = ""
            while True:
                params = {"action": "query", "list": "allpages", "apnamespace": ns, "aplimit": "20", "format": "json", "apcontinue": apcontinue}
                res = session.get(API_URL, params=params).json()
                pages = res.get('query', {}).get('allpages', [])
                if not pages: break

                pids = [str(p['pageid']) for p in pages]
                
                # 상세 데이터 + 이미지 목록 조회
                p_params = {
                    "action": "query", "pageids": "|".join(pids),
                    "prop": "revisions|images|categories|info",
                    "rvprop": "content", "rvslots": "main", "format": "json"
                }
                res_p = session.get(API_URL, params=p_params).json()
                pages_detail = res_p.get('query', {}).get('pages', {})

                for pid in pids:
                    p_info = pages_detail.get(pid, {})
                    title = p_info.get('title', 'N/A')
                    
                    # 3. 이미지 정보 조회 및 URL 추출
                    image_titles = [img.get('title') for img in p_info.get('images', [])]
                    image_urls = []

                    if image_titles:
                        img_params = {"action": "query", "titles": "|".join(image_titles), "prop": "imageinfo", "iiprop": "url", "format": "json"}
                        res_img = session.get(API_URL, params=img_params).json()
                        img_pages = res_img.get('query', {}).get('pages', {}).values()
                        for img_page in img_pages:
                            if 'imageinfo' in img_page:
                                image_urls.append(img_page['imageinfo'][0]['url'])

                    # [핵심] p_info 객체에 image_urls 리스트를 직접 추가!
                    p_info['image_urls'] = image_urls

                    # 종류 및 분류 처리
                    kind = "일반" if ns == 0 else ("틀" if ns == 10 else "분류")
                    if "redirect" in p_info: kind += " (넘겨주기)"
                    cats = p_info.get('categories', [])
                    cat_names = ", ".join([c.get('title', '').replace('분류:', '') for c in cats])

                    # JSON 데이터 분할 (기존 인덱스 4번부터 시작하게 함)
                    raw_json = json.dumps(p_info, ensure_ascii=False)
                    json_parts = [raw_json[i:i+45000] for i in range(0, len(raw_json), 45000)]
                    
                    # [구조 유지] ID(0), 제목(1), 종류(2), 분류(3), JSON_PART1(4)...
                    all_rows.append([pid, title, kind, cat_names] + json_parts)

                if 'continue' in res:
                    apcontinue = res['continue']['apcontinue']
                else: break

        # [4] 시트 업데이트
        if all_rows:
            sheet.clear()
            max_col = max(len(r) for r in all_rows)
            header = ["ID", "제목", "종류", "분류"] + [f"JSON_{i}" for i in range(1, max_col - 3)]
            sheet.append_row(header)
            for i in range(0, len(all_rows), 50):
                sheet.append_rows(all_rows[i:i+50])
            send_discord_bot_message(f"✅ 동기화 완료! 이미지 URL이 JSON 내부에 포함되었습니다.")

    except Exception as e:
        send_discord_bot_message(f"🔥 에러: {str(e)}")

if __name__ == "__main__":
    run_sync()
