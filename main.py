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
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).get_worksheet(0)

        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        session.headers.update({"User-Agent": "WikiDataSync_Final/3.0"})

        # 로그인 인증
        res_t = session.get(API_URL, params={"action": "query", "meta": "tokens", "type": "login", "format": "json"}).json()
        l_token = res_t['query']['tokens']['logintoken']
        session.post(API_URL, data={"action": "login", "lgname": WIKI_USER, "lgpassword": WIKI_PASS, "lgtoken": l_token, "format": "json"})

        all_rows = []
        # 네임스페이스 정의: 0(일반), 10(틀), 14(분류)
        target_namespaces = [0, 10, 14]
        
        for ns in target_namespaces:
            apcontinue = ""
            ns_count = 0
            ns_label = "일반" if ns == 0 else ("틀" if ns == 10 else "분류")
            
            send_discord_bot_message(f"📡 {ns_label} 문서 수집 시작...")
            
            while True:
                # aplimit를 50으로 상향하여 더 안정적으로 가져옴
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

                pids = [str(p['pageid']) for p in pages]
                
                # 상세 정보 및 이미지 조회 (이미지 정보를 revisions와 함께 가져오도록 최적화)
                p_params = {
                    "action": "query",
                    "pageids": "|".join(pids),
                    "prop": "revisions|images|categories|info",
                    "rvprop": "content",
                    "rvslots": "main",
                    "format": "json"
                }
                res_p = session.get(API_URL, params=p_params).json()
                pages_detail = res_p.get('query', {}).get('pages', {})

                for pid in pids:
                    p_info = pages_detail.get(pid, {})
                    title = p_info.get('title', 'N/A')
                    
                    # 이미지 URL 추출 (없을 경우 빈 리스트)
                    image_titles = [img.get('title') for img in p_info.get('images', [])]
                    image_urls = []

                    if image_titles:
                        # 파일 제목들을 50개씩 묶어서 한 번에 URL 조회 (속도 향상)
                        img_params = {"action": "query", "titles": "|".join(image_titles), "prop": "imageinfo", "iiprop": "url", "format": "json"}
                        res_img = session.get(API_URL, params=img_params).json()
                        if 'query' in res_img:
                            for img_page in res_img['query'].get('pages', {}).values():
                                if 'imageinfo' in img_page:
                                    image_urls.append(img_page['imageinfo'][0]['url'])

                    # JSON에 이미지 URL 직접 삽입
                    p_info['image_urls'] = image_urls

                    # 종류 및 분류
                    kind = ns_label
                    if "redirect" in p_info: kind += " (넘겨주기)"
                    cats = p_info.get('categories', [])
                    cat_names = ", ".join([c.get('title', '').replace('분류:', '') for c in cats])

                    # 데이터 분할 (기존 인덱스 4번 유지)
                    raw_json = json.dumps(p_info, ensure_ascii=False)
                    json_parts = [raw_json[i:i+45000] for i in range(0, len(raw_json), 45000)]
                    
                    all_rows.append([pid, title, kind, cat_names] + json_parts)
                    ns_count += 1

                if 'continue' in res:
                    apcontinue = res['continue']['apcontinue']
                    time.sleep(0.5) # 서버 부하 방지
                else:
                    break
            
            send_discord_bot_message(f"✅ {ns_label} 수집 완료: {ns_count}건")

        # [4] 시트 업데이트
        if all_rows:
            sheet.clear()
            max_col = max(len(r) for r in all_rows)
            header = ["ID", "제목", "종류", "분류"] + [f"JSON_{i}" for i in range(1, max_col - 3)]
            sheet.append_row(header)
            
            # 구글 시트 API 할당량 초과 방지를 위해 40행씩 끊어서 입력
            for i in range(0, len(all_rows), 40):
                sheet.append_rows(all_rows[i:i+40])
                time.sleep(1)
            
            send_discord_bot_message(f"🚀 전체 동기화 성공! 총 {len(all_rows)}건 업데이트 완료.")
        else:
            send_discord_bot_message("⚠️ 수집된 데이터가 없습니다. (NS 수집 실패)")

    except Exception as e:
        send_discord_bot_message(f"🔥 에러: {str(e)}")

if __name__ == "__main__":
    run_sync()
