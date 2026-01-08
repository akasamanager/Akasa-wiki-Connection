import os, requests, gspread, json, time, re
from oauth2client.service_account import ServiceAccountCredentials

# 설정 (기존과 동일)
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
        session.headers.update({"User-Agent": "WikiDataSync_Final_Details/4.0"})

        # 로그인
        res_t = session.get(API_URL, params={"action": "query", "meta": "tokens", "type": "login", "format": "json"}).json()
        l_token = res_t['query']['tokens']['logintoken']
        session.post(API_URL, data={"action": "login", "lgname": WIKI_USER, "lgpassword": WIKI_PASS, "lgtoken": l_token, "format": "json"})

        all_rows = []
        target_namespaces = [0, 10, 14]
        
        for ns in target_namespaces:
            apcontinue = ""
            while True:
                params = {"action": "query", "list": "allpages", "apnamespace": ns, "aplimit": "50", "format": "json", "apcontinue": apcontinue}
                res = session.get(API_URL, params=params).json()
                pages = res.get('query', {}).get('allpages', [])
                if not pages: break

                pids = [str(p['pageid']) for p in pages]
                p_params = {"action": "query", "pageids": "|".join(pids), "prop": "revisions|images|categories|info", "rvprop": "content", "rvslots": "main", "format": "json"}
                res_p = session.get(API_URL, params=p_params).json()
                pages_detail = res_p.get('query', {}).get('pages', {})

                for pid in pids:
                    p_info = pages_detail.get(pid, {})
                    content = p_info.get('revisions', [{}])[0].get('slots', {}).get('main', {}).get('*', '')
                    
                    # [핵심] 이미지 구문과 캡션 추출 (정규표현식)
                    # [[파일:이름.png|옵션|설명]] 형태를 찾아냅니다.
                    img_pattern = re.findall(r'\[\[(?:파일|File|파일):([^|\]]+)(?:\|([^\]]+))?\]\]', content)
                    
                    details_list = []
                    image_titles = []
                    
                    # 먼저 파일 이름들만 모아서 URL 한꺼번에 조회 준비
                    for ititle, ioptions in img_pattern:
                        full_name = f"파일:{ititle.strip()}"
                        image_titles.append(full_name)
                    
                    # 실제 URL 조회
                    url_map = {}
                    if image_titles:
                        img_res = session.get(API_URL, params={"action": "query", "titles": "|".join(image_titles), "prop": "imageinfo", "iiprop": "url", "format": "json"}).json()
                        for img_page in img_res.get('query', {}).get('pages', {}).values():
                            if 'imageinfo' in img_page:
                                url_map[img_page['title']] = img_page['imageinfo'][0]['url']

                    # 매칭 작업 (URL + 캡션)
                    for ititle, ioptions in img_pattern:
                        full_name = f"파일:{ititle.strip()}"
                        url = url_map.get(full_name, "")
                        
                        # 옵션 중 마지막 요소가 보통 캡션(설명)임
                        caption = ""
                        if ioptions:
                            opts = ioptions.split('|')
                            # '섬네일', 'thumb', 'left' 등 예약어 제외한 마지막이 설명
                            last_opt = opts[-1].strip()
                            if not any(keyword in last_opt for keyword in ['섬네일', 'thumb', 'left', 'right', 'center', 'px']):
                                caption = last_opt
                        
                        details_list.append({
                            "url": url,
                            "filename": ititle.strip(),
                            "caption": caption
                        })

                    # JSON 데이터에 상세 리스트 삽입
                    p_info['image_details'] = details_list

                    kind = "일반" if ns == 0 else ("틀" if ns == 10 else "분류")
                    cats = p_info.get('categories', [])
                    cat_names = ", ".join([c.get('title', '').replace('분류:', '') for c in cats])

                    raw_json = json.dumps(p_info, ensure_ascii=False)
                    all_rows.append([pid, p_info.get('title', 'N/A'), kind, cat_names, raw_json])

                if 'continue' in res: apcontinue = res['continue']['apcontinue']
                else: break

        # [4] 시트 업데이트 (기존 구조 유지)
        if all_rows:
            sheet.clear()
            sheet.append_row(["ID", "제목", "종류", "분류", "JSON"])
            for i in range(0, len(all_rows), 40):
                sheet.append_rows(all_rows[i:i+40])
                time.sleep(1)
            send_discord_bot_message(f"✅ 동기화 완료! 이미지 위치와 설명이 JSON에 포함되었습니다.")

    except Exception as e:
        send_discord_bot_message(f"🔥 에러: {str(e)}")

if __name__ == "__main__":
    run_sync()
