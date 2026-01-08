import os, requests, gspread, json, time, re
from oauth2client.service_account import ServiceAccountCredentials

# 설정 (기존 환경변수 사용)
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
        # [1] 구글 시트 연결 및 안정화
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).get_worksheet(0)

        # [2] 위키 API 세션 (헤더 강화)
        API_URL = "https://akasauniverse.miraheze.org/w/api.php"
        session = requests.Session()
        session.headers.update({"User-Agent": "WikiSyncExpert/5.0 (Final Stable)"})

        # 로그인 토큰 및 인증
        res_t = session.get(API_URL, params={"action": "query", "meta": "tokens", "type": "login", "format": "json"}).json()
        l_token = res_t['query']['tokens']['logintoken']
        session.post(API_URL, data={"action": "login", "lgname": WIKI_USER, "lgpassword": WIKI_PASS, "lgtoken": l_token, "format": "json"})

        all_rows = []
        target_namespaces = [0, 10, 14]
        
        for ns in target_namespaces:
            apcontinue = ""
            ns_label = "일반" if ns == 0 else ("틀" if ns == 10 else "분류")
            send_discord_bot_message(f"📡 {ns_label} 문서 동기화 시도 중...")

            while True:
                # 안전을 위해 aplimit를 25로 하향 조절 (한 번에 너무 많은 데이터 방지)
                params = {"action": "query", "list": "allpages", "apnamespace": ns, "aplimit": "25", "format": "json", "apcontinue": apcontinue}
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
                    
                    # 캡션 추출 로직
                    img_pattern = re.findall(r'\[\[(?:파일|File):([^|\]]+)(?:\|([^\]]+))?\]\]', content)
                    details_list = []
                    image_titles = [f"파일:{it[0].strip()}" for it in img_pattern]
                    
                    url_map = {}
                    if image_titles:
                        # 파일 정보를 쿼리할 때는 조심스럽게
                        img_res = session.get(API_URL, params={"action": "query", "titles": "|".join(image_titles), "prop": "imageinfo", "iiprop": "url", "format": "json"}).json()
                        for img_page in img_res.get('query', {}).get('pages', {}).values():
                            if 'imageinfo' in img_page:
                                url_map[img_page['title']] = img_page['imageinfo'][0]['url']

                    for ititle, ioptions in img_pattern:
                        full_name = f"파일:{ititle.strip()}"
                        caption = ""
                        if ioptions:
                            opts = ioptions.split('|')
                            last_opt = opts[-1].strip()
                            if not any(k in last_opt for k in ['섬네일', 'thumb', 'left', 'right', 'center', 'px', '프레임']):
                                caption = last_opt
                        
                        details_list.append({"url": url_map.get(full_name, ""), "filename": ititle.strip(), "caption": caption})

                    p_info['image_details'] = details_list
                    kind = ns_label
                    if "redirect" in p_info: kind += " (넘겨주기)"
                    cats = p_info.get('categories', [])
                    cat_names = ", ".join([c.get('title', '').replace('분류:', '') for c in cats])

                    # JSON 분할 저장 (안정성 강화)
                    raw_json = json.dumps(p_info, ensure_ascii=False)
                    # 시트 셀 당 최대 글자수 제한(32767)을 고려하여 30000자씩 분할
                    json_parts = [raw_json[i:i+30000] for i in range(0, len(raw_json), 30000)]
                    
                    all_rows.append([pid, p_info.get('title', 'N/A'), kind, cat_names] + json_parts)

                if 'continue' in res:
                    apcontinue = res['continue']['apcontinue']
                else: break

        # [3] 구글 시트 업데이트 (분할 업데이트 전략)
        if all_rows:
            sheet.clear()
            # 헤더 생성
            max_col = max(len(r) for r in all_rows)
            header = ["ID", "제목", "종류", "분류"] + [f"JSON_{i}" for i in range(1, max_col - 3)]
            sheet.append_row(header)
            
            # 🚀 핵심: 20행씩 매우 보수적으로 입력 (누락 방지)
            for i in range(0, len(all_rows), 20):
                sheet.append_rows(all_rows[i:i+20])
                time.sleep(2) # 구글 API 할당량 회복 대기
            
            send_discord_bot_message(f"✅ 전체 동기화 성공! 총 {len(all_rows)}개 문서 로드됨.")
        else:
            send_discord_bot_message("⚠️ 수집된 데이터가 0건입니다.")

    except Exception as e:
        send_discord_bot_message(f"🔥 치명적 에러 발생: {str(e)}")

if __name__ == "__main__":
    run_sync()
