"""
MQS ChatPilot - Cloud Webhook Server with Gemini AI Integration
Deployed to Render: https://mqs-chatpilot.onrender.com
"""
import os, json, re, time, random, hashlib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, redirect, send_from_directory
import requests

def resource_path(p): return os.path.join(os.path.dirname(__file__), p)

CONFIG_PATH = resource_path("config.json")
CLIENTS_PATH = resource_path("clients.json")
BOOKINGS_PATH = resource_path("bookings.json")
SESSIONS_PATH = resource_path("sessions.json")
USERS_PATH = resource_path("users.json")

def load_clients():
    if os.path.exists(CLIENTS_PATH):
        try:
            with open(CLIENTS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data: return data
        except: pass
    if os.path.exists(CONFIG_PATH):
        try:
            cfg = json.load(open(CONFIG_PATH, encoding='utf-8'))
            return [{"id":"balsa_1","name":cfg.get("business_info",{}).get("name","Balsa 1"),"page_id":"","config":cfg}]
        except: pass
    return []

_env_page = os.environ.get("PAGE_TOKEN") or os.environ.get("PAGE_ACCESS_TOKEN")
# support GEMINI_KEY as comma-separated or GEMINI_KEY_1, _2, _3...
_env_keys = []
for _i in range(1, 10):
    _k = os.environ.get(f"GEMINI_KEY_{_i}")
    if _k: _env_keys.append(_k.strip())
_main = os.environ.get("GEMINI_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
if _main:
    _env_keys.extend([k.strip() for k in _main.split(",") if k.strip()])
# fallback to old hardcoded only if no env at all (for local testing)
_env_key = ",".join(_env_keys) if _env_keys else "sk-df1543af0a48b86d-664eae-f73acc9e"
_env_verify = os.environ.get("VERIFY_TOKEN")
_env_pid = os.environ.get("PAGE_ID")
print(f"[INIT] GEMINI keys loaded: {len(_env_keys)} key(s), first len={len(_env_keys[0]) if _env_keys else 0}", flush=True)

clients = load_clients()
if not clients and _env_page:
    clients = [{
        "id": "balsa_1", "name": "Balsa ni Mac",
        "page_id": _env_pid or "1337624369425179",
        "config": {
            "page_access_token": _env_page,
            "verify_token": _env_verify or "mqs_verify_2026",
            "ai_api_key": _env_key,
            "port": 5000,
            "business_info": {
                "name": "Balsa ni Mac", "location": "Calatagan, Batangas",
                "price_day": "3500 (7am-4pm)", "price_day_amount": "3500",
                "capacity": "15-20 pax",
                "inclusions": "Floating cottage, videoke, ihawan, life vest, lutuan",
                "contact": "09123456789",
                "gcash_number": "09123456789", "gcash_name": "Mac David Bernal",
                "downpayment": "1000",
                "google_maps_link": "https://maps.app.goo.gl/DITO",
                "balsa_photos_url": "https://facebook.com/balsa",
                "dti_permit_url": "https://drive.google.com/permit",
                "extra_info": "Day Tour 7am-4pm",
                "cancellation_policy": "No refund 1 day before",
                "owner_fb_id": ""
            },
            "ai_system_prompt": ""
        }
    }]
elif _env_page and clients:
    clients[0]["config"]["page_access_token"] = _env_page
    if _env_pid: clients[0]["page_id"] = _env_pid

for c in clients:
    c["config"]["ai_api_key"] = _env_key

def get_client_by_page_id(pid):
    if not pid: return None
    for c in clients:
        if str(c.get("page_id","")) == str(pid): return c
    return None

sessions = {}
seen_message_ids = {}

def load_sessions():
    global sessions
    if os.path.exists(SESSIONS_PATH):
        try: sessions = json.load(open(SESSIONS_PATH, encoding="utf-8"))
        except: sessions = {}
def save_sessions():
    try:
        with open(SESSIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except: pass
load_sessions()

# === AUTO-REMINDER + REVIEW REQUEST (Meta-safe tags) ===
import threading as _th2
from datetime import timedelta

def parse_booking_date(date_str):
    """Parse flexible date like 2026-08-30, 08/30, Aug 30, Aug 30 2026 -> date obj or None"""
    if not date_str: return None
    import datetime as _dt, re as _re
    s = str(date_str).strip().lower()
    # YYYY-MM-DD
    m = _re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try: return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except: pass
    # MM/DD[/YY]
    m = _re.match(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", s)
    if m:
        try:
            mm, dd = int(m.group(1)), int(m.group(2))
            yy = m.group(3)
            y = int(yy) if yy else _dt.date.today().year
            if y < 100: y += 2000
            return _dt.date(y, mm, dd)
        except: pass
    # Month name + day
    months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
    for k,v in months.items():
        mm = _re.search(k + r"\s*(\d{1,2})", s)
        if mm:
            try:
                d = int(mm.group(1))
                now = _dt.date.today()
                y = now.year
                # if month/day already passed this year, assume next year
                try:
                    cand = _dt.date(y, v, d)
                    if cand < now: cand = _dt.date(y+1, v, d)
                    return cand
                except: return _dt.date(y, v, d)
            except: pass
    return None

def run_reminders_and_reviews():
    """Check bookings for tomorrow (reminder) and yesterday (review). Uses Meta MESSAGE_TAG."""
    import datetime as _dt
    today = _dt.date.today()
    tomorrow = today + _dt.timedelta(days=1)
    yesterday = today - _dt.timedelta(days=1)
    for client in clients:
        biz = client["config"].get("business_info",{})
        bookings = load_bookings(client["id"])
        changed = False
        for b in bookings:
            if b.get("status") not in ["CONFIRMED","PAID_AWAITING_CONFIRM"]:
                continue
            fb_id = b.get("customer_fb_id","")
            if not fb_id or fb_id=="MANUAL" or not fb_id.isdigit():
                continue
            bdate = parse_booking_date(b.get("date",""))
            if not bdate: continue
            # --- Reminder 1 day before ---
            if bdate == tomorrow and not b.get("reminder_sent"):
                msg = f"Hi {b.get('customer_name','Mam/Sir')}! 👋 Reminder lang po — bukas na ({b.get('date')}) ang Day Tour nyo sa {biz.get('name','')} ({b.get('pax','')} pax, 7am-4pm). Kitakits! 🌊 Dalhin ang food, sunblock, Valid ID. Contact owner {biz.get('contact','')} kung may tanong."
                # Meta tag: CONFIRMED_EVENT_UPDATE is safest for reminders
                ok = send_fb_message(client, fb_id, msg, tag="CONFIRMED_EVENT_UPDATE")
                if not ok:
                    ok = send_fb_message(client, fb_id, msg)
                if ok:
                    b["reminder_sent"] = True
                    b["reminder_sent_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    changed = True
                    print(f"[REMINDER] Sent to {b.get('customer_name')} {b.get('date')} fb:{fb_id}", flush=True)
                else:
                    print(f"[REMINDER] Failed {b.get('id')} fb:{fb_id}", flush=True)
            # --- Review request 1 day after ---
            if bdate == yesterday and not b.get("review_sent"):
                # check if today is after booking (already past)
                msg2 = f"Salamat {b.get('customer_name','Mam/Sir')} sa pagbisita sa {biz.get('name','')} kahapon! 🙏 Kumusta po ang balsa & service? Pwede po kayo mag-iwan ng review sa FB page namin — malaking tulong po sa amin! ⭐ Salamat ulit, balik kayo! 🌊"
                ok2 = send_fb_message(client, fb_id, msg2, tag="POST_PURCHASE_UPDATE")
                if not ok2:
                    ok2 = send_fb_message(client, fb_id, msg2)
                if ok2:
                    b["review_sent"] = True
                    b["review_sent_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    changed = True
                    print(f"[REVIEW] Sent to {b.get('customer_name')} {b.get('date')}", flush=True)
        if changed:
            path = resource_path(f"bookings_{client['id']}.json")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(bookings, f, indent=4, ensure_ascii=False)
                with open(BOOKINGS_PATH, "w", encoding="utf-8") as f:
                    json.dump(bookings, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[REMINDER] save error {e}", flush=True)

def _reminder():
    import time
    # wait 60s on start, then hourly
    time.sleep(60)
    while True:
        try: run_reminders_and_reviews()
        except Exception as e: print(f"[REMINDER] loop error {e}", flush=True)
        time.sleep(3600)
_th2.Thread(target=_reminder, daemon=True).start()
print('[INIT] Reminder+Review loop started (60s delay, then hourly)', flush=True)

def send_owner_notif(client, booking, kind="BOOKING"):
    """Owner notif for cloud - FB + Telegram if configured, otherwise just log"""
    biz = client["config"].get("business_info",{})
    owner_id = biz.get("owner_fb_id","").strip()
    if kind == "INQUIRY":
        msg = f"🔔 NEW INQUIRY (cloud) - {biz.get('name','')}\n👤 {booking.get('customer_name','')} - {booking.get('contact','')} (FB:{booking.get('customer_fb_id','')})\n📅 {booking.get('date','')} | 👥 {booking.get('pax','')} pax"
    elif kind == "PHOTO_REQUEST":
        msg = f"📸 Photo request - {biz.get('name','')}\n👤 {booking.get('customer_name','')} FB:{booking.get('customer_fb_id','')} asked for balsa photos"
    else:
        msg = f"📝 NEW BOOKING (cloud) - {biz.get('name','')}\n👤 {booking.get('customer_name','')} - {booking.get('contact','')}\n📅 {booking.get('date','')} | {booking.get('pax','')} pax"
    print(f"[OWNER_NOTIF {kind}] {msg[:140]}", flush=True)
    if owner_id and owner_id.isdigit():
        token = client["config"].get("page_access_token","")
        if token:
            try:
                url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
                r = requests.post(url, json={"recipient":{"id": owner_id}, "message":{"text": msg}}, timeout=10)
                print(f"[OWNER_NOTIF] FB {r.status_code}", flush=True)
            except Exception as e:
                print(f"[OWNER_NOTIF] FB error {e}", flush=True)
    tg_token = biz.get("owner_telegram_token","").strip()
    tg_chat = biz.get("owner_telegram_chat_id","").strip()
    if tg_token and tg_chat:
        try:
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            r = requests.post(url, json={"chat_id": tg_chat, "text": msg}, timeout=10)
            print(f"[OWNER_NOTIF] TG {r.status_code}", flush=True)
        except Exception as e:
            print(f"[OWNER_NOTIF] TG error {e}", flush=True)

def load_bookings(client_id):
    """Load bookings for a client (cloud helper)"""
    import glob as _glob
    path = resource_path(f"bookings_{client_id}.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list): return data
        except: pass
    if os.path.exists(BOOKINGS_PATH):
        try:
            with open(BOOKINGS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list): return data
        except: pass
    return []

def load_blocked_dates_server(client_id):
    p = resource_path(f"blocked_{client_id}.json")
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list): return data
        except: pass
    return []

def is_vacation_active_server(client):
    if not client["config"].get("vacation_enabled"): return False, None
    until = client["config"].get("vacation_until","").strip()
    if not until: return True, client["config"].get("vacation_reason","Vacation")
    try:
        import datetime as _dt
        for fmt in ("%Y-%m-%d","%m/%d/%Y","%d/%m/%Y"):
            try:
                d = _dt.datetime.strptime(until, fmt).date()
                if _dt.date.today() <= d:
                    return True, client["config"].get("vacation_reason","Vacation")
                else:
                    return False, None
            except: continue
        return True, client["config"].get("vacation_reason","Vacation")
    except: return True, client["config"].get("vacation_reason","Vacation")

def is_date_blocked_server(client, date_str):
    is_vac, reason = is_vacation_active_server(client)
    if is_vac:
        until = client["config"].get("vacation_until","")
        return True, f"Vacation ({reason}) until {until}" if until else f"Vacation ({reason})", {"id":"VACATION","reason":reason}
    try:
        import datetime as _dt
        qdate = parse_booking_date(date_str)
        if not qdate: return False, None, None
        for blk in load_blocked_dates_server(client["id"]):
            try:
                s = _dt.datetime.strptime(blk.get("start",""), "%Y-%m-%d").date()
                e = _dt.datetime.strptime(blk.get("end",""), "%Y-%m-%d").date()
                if s <= qdate <= e:
                    return True, blk.get("reason","Blocked"), blk
            except: continue
    except: pass
    return False, None, None


# === GOOGLE CALENDAR HELPERS ===
def is_calendar_available(client, date_str):
    biz = client["config"]["business_info"]
    cal_id = biz.get("google_calendar_id","").strip()
    api_key = biz.get("google_calendar_api_key","").strip()
    if not cal_id or not api_key:
        return None  # no calendar configured, fallback to local
    # parse date like "dec 2" or "2026-12-02" or "nov 3"
    import datetime, re
    # try to parse
    try:
        # normalize date to YYYY-MM-DD
        low = date_str.lower().strip()
        # try direct YYYY-MM-DD
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", low)
        if m:
            y,mth,d = m.groups()
            dt = datetime.datetime(int(y), int(mth), int(d))
        else:
            # try "dec 2" or "nov 3"
            months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
            for k,v in months.items():
                mm = re.search(k + r"\s*(\d{1,2})", low)
                if mm:
                    d = int(mm.group(1))
                    # assume current year or next year if past
                    now = datetime.datetime.now()
                    y = now.year
                    # if month already passed, assume next year
                    if v < now.month or (v==now.month and d < now.day):
                        y += 1
                    dt = datetime.datetime(y, v, d)
                    break
            else:
                return None
        # query calendar for that day
        start = dt.strftime("%Y-%m-%dT00:00:00Z")
        end = dt.strftime("%Y-%m-%dT23:59:59Z")
        import requests, urllib.parse
        url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(cal_id)}/events?key={api_key}&timeMin={start}&timeMax={end}&singleEvents=true&maxResults=10"
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            print(f"[CAL] read fail {r.status_code}: {r.text[:100]}", flush=True)
            return None
        events = r.json().get("items", [])
        # count events that look like bookings (not empty)
        booked = len([e for e in events if "summary" in e])
        max_balsas = int(biz.get("number_of_balsas","1") or 1)
        print(f"[CAL] {date_str} -> {booked}/{max_balsas} booked", flush=True)
        return booked < max_balsas
    except Exception as e:
        print(f"[CAL] error {e}", flush=True)
        return None

def create_calendar_event(client, date_str, summary, description):
    biz = client["config"]["business_info"]
    cal_id = biz.get("google_calendar_id","").strip()
    api_key = biz.get("google_calendar_api_key","").strip()
    if not cal_id or not api_key:
        print("[CAL] no calendar configured for create", flush=True)
        return False
    # For now, just log - real create needs OAuth service account.
    # We will try to create via API key if calendar allows (public writable), but usually needs OAuth.
    # So we just log and also notify owner to manually add.
    print(f"[CAL] Would create event {date_str}: {summary} - {description}", flush=True)
    # Try to create via API key (may fail if not writable, but we try)
    try:
        import datetime, re, requests, urllib.parse
        low = date_str.lower().strip()
        months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
        dt = None
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", low)
        if m:
            y,mth,d = m.groups()
            dt = datetime.datetime(int(y), int(mth), int(d), 8, 0, 0)
        else:
            for k,v in months.items():
                mm = re.search(k + r"\s*(\d{1,2})", low)
                if mm:
                    d = int(mm.group(1))
                    now = datetime.datetime.now()
                    y = now.year
                    if v < now.month: y+=1
                    dt = datetime.datetime(y, v, d, 8, 0, 0)
                    break
        if not dt: return False
        end = dt.replace(hour=16)
        payload = {"summary": summary, "description": description, "start": {"dateTime": dt.isoformat()+"Z"}, "end": {"dateTime": end.isoformat()+"Z"}}
        url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(cal_id)}/events?key={api_key}"
        r = requests.post(url, json=payload, timeout=8)
        print(f"[CAL] create status {r.status_code}: {r.text[:120]}", flush=True)
        return r.status_code == 200
    except Exception as e:
        print(f"[CAL] create error {e}", flush=True)
        return False

def get_available_balsa_photo(client, date_str):
    # if multiple balsas, return photo of an available one
    # For now, just return the main photos link, or parse JSON per balsa
    biz = client["config"]["business_info"]
    try:
        import json as _js
        photos_json = biz.get("balsa_photos_json","")
        if photos_json:
            d = _js.loads(photos_json)
            # find first available balsa not booked for date - simplified: just return first
            for k,v in d.items():
                return v
    except: pass
    return biz.get("balsa_photos_url","")

def get_fb_user_name(client, sender_id):
    token = client["config"].get("page_access_token", "")
    if not token: return ""
    url = f"https://graph.facebook.com/v19.0/{sender_id}?fields=first_name&access_token={token}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            name = r.json().get("first_name", "").strip()
            if name: return name
    except:
        pass
    return ""

def send_fb_message(client, recipient_id, text, tag=None):
    token = client["config"].get("page_access_token","")
    if not token: return False
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
    payload = {"recipient":{"id":recipient_id},"message":{"text":text}}
    if tag:
        payload["messaging_type"] = "MESSAGE_TAG"
        payload["tag"] = tag
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[FB SEND] fail {r.status_code}: {r.text[:120]}", flush=True)
        return r.status_code == 200
    except Exception as e:
        print(f"[FB SEND] error {e}", flush=True)
        return False

# === GCASH SCREENSHOT AUTO-VERIFY (AI Vision) ===
def verify_gcash_image(image_bytes, biz, api_key):
    """Use Gemini Vision to extract Ref No / Amount from GCash screenshot. Returns dict or None."""
    if not image_bytes or not api_key:
        return None
    import base64
    keys = [k.strip() for k in api_key.split(",") if k.strip()]
    if not keys: return None
    prompt = (
        "You are a GCash receipt OCR. Extract from this GCash screenshot:\n"
        "- Reference Number (9-13 digits)\n"
        "- Amount (e.g., 1000.00)\n"
        "- Date/Time if visible\n"
        "- Sender/Receiver name if visible\n"
        "Return ONLY JSON: {\"ref\":\"...\", \"amount\":\"...\", \"date\":\"...\", \"sender\":\"...\", \"receiver\":\"...\", \"confident\": true/false}\n"
        f"Expected GCash receiver: {biz.get('gcash_number','')} ({biz.get('gcash_name','')}), expected down {biz.get('downpayment','1000')}.\n"
        "If clearly GCash receipt, confident=true else false."
    )
    b64 = base64.b64encode(image_bytes).decode()
    # Try google.genai vision - use ONLY latest models (3.6 + flash-latest), 2.5/1.5 are 404 now
    last_status = None
    for idx, key in enumerate(keys):
        if idx > 0:
            if last_status == 429:
                print(f"[GCASH VISION] Quota hit, instant switch to key {idx+1}/{len(keys)}", flush=True)
            elif last_status == 503:
                time.sleep(0.4)
        try:
            from google import genai as genai_new
            from google.genai import types
            client_ai = genai_new.Client(api_key=key)
            for mdl in ["gemini-3.6-flash", "gemini-flash-latest"]:
                try:
                    resp = client_ai.models.generate_content(
                        model=mdl,
                        contents=[
                            types.Content(role="user", parts=[
                                types.Part.from_text(text=prompt),
                                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
                            ])
                        ]
                    )
                    txt = (resp.text or "").strip()
                    m = re.search(r"\{.*?\}", txt, re.S)
                    if m:
                        j = json.loads(m.group(0))
                        if j.get("ref"):
                            print(f"[GCASH VISION] {mdl} success ref={j.get('ref')} amt={j.get('amount')}", flush=True)
                            return j
                    print(f"[GCASH VISION] {mdl} no ref in: {txt[:100]}", flush=True)
                    last_status = 200
                except Exception as e:
                    msg = str(e)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                        last_status = 429
                        print(f"[GCASH VISION] {mdl} 429 quota, try next key", flush=True)
                        break
                    elif "503" in msg:
                        last_status = 503
                        print(f"[GCASH VISION] {mdl} 503, try next model", flush=True)
                        continue
                    else:
                        last_status = 400
                        print(f"[GCASH VISION] {mdl} error {e}", flush=True)
                        break
        except Exception as e:
            print(f"[GCASH VISION] genai error {e}", flush=True)
            last_status = 400
        # REST fallback - also only latest models
        try:
            for mdl in ["gemini-3.6-flash", "gemini-flash-latest"]:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={key}"
                payload = {"contents":[{"role":"user","parts":[{"text":prompt},{"inline_data":{"mime_type":"image/jpeg","data":b64}}]}]}
                r = requests.post(url, json=payload, timeout=15)
                if r.status_code==200:
                    txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    m = re.search(r"\{.*?\}", txt, re.S)
                    if m:
                        j = json.loads(m.group(0))
                        if j.get("ref"):
                            print(f"[GCASH VISION REST] {mdl} success", flush=True)
                            return j
                    last_status = 200
                elif r.status_code==429:
                    last_status = 429
                    print(f"[GCASH VISION REST] {mdl} 429", flush=True)
                    break
                elif r.status_code==503:
                    last_status = 503
                    print(f"[GCASH VISION REST] {mdl} 503", flush=True)
                    continue
                else:
                    last_status = r.status_code
                    print(f"[GCASH VISION REST] {mdl} {r.status_code}: {r.text[:80]}", flush=True)
                    break
        except Exception as e:
            print(f"[GCASH VISION REST] error {e}", flush=True)
    return None

def download_fb_image(url, token):
    """Download image from FB CDN using page token"""
    try:
        # FB image url may need token appended
        r = requests.get(url, timeout=15)
        if r.status_code==200 and r.content:
            return r.content
        print(f"[DL IMAGE] fail {r.status_code}", flush=True)
    except Exception as e:
        print(f"[DL IMAGE] error {e}", flush=True)
    return None

def call_ai(api_key, biz, history, text, user_name):
    if not api_key: return None
    keys = [k.strip() for k in api_key.split(",") if k.strip()]
    if not keys: return None
    system_instruction = (
        f"You are the friendly and cheerful chat assistant of {biz.get('name')} located in {biz.get('location')}. "
        f"The user's name is {user_name}. "
        f"Rules:\n"
        f"1. **Language Matching:** Match the language used by the customer. If they speak Tagalog/Taglish, reply in Tagalog/Taglish. If they speak English, reply in fluent English.\n"
        f"2. **Greetings:** ONLY greet with 'Hello Mam/Sir {user_name}' if it is the VERY FIRST message (history length 1-2). In the middle of conversation, DO NOT greet again, just answer directly.\n"
        f"3. **Direct & Specific Answers (STRICT):** Sagutin LANG ang eksaktong tinatanong ng customer. HUWAG magsasama ng presyo, oras, o inclusions kung ang tinatanong lang ay kung ilan ang kasya (capacity). Halimbawa, kung tinanong kung ilan ang kasya, sabihin lang na good for {biz.get('capacity')} at huwag nang magbanggit ng rate o oras hangga't hindi tinatanong.\n"
        f"4. **No Entrance Fee:** Walang hiwalay na entrance fee sa balsa. Ang meron ay ang package rate na P{biz.get('price_day_amount')} para sa Day Tour (7:00 AM - 4:00 PM) na kasama na ang {biz.get('inclusions')}. May hiwalay lang na ecological fee (mga P30) sa port/munisipyo.\n"
        f"5. **No Premature Downpayment:** DO NOT mention downpayment or GCash when they are just asking about capacity, entrance fees, rates, availability dates, inclusions, food, or headcount. Answer their specific questions directly first.\n"
        f"6. **Booking Confirmation Only:** Only mention the P{biz.get('downpayment')} downpayment and GCash details ({biz.get('gcash_number')} - {biz.get('gcash_name')}) at the very end when they explicitly confirm they want to book.\n"
        f"7. **Day Tour Only:** Day Tour only (7:00 AM - 4:00 PM). No overnight stay.\n"
        f"8. **Location / Address Inquiry:** Kapag nagtanong lang ang customer ng 'location po?' o 'saan kayo?', sabihin na kami ay matatagpuan sa {biz.get('location')} at ibigay ang Google Maps link: {biz.get('google_maps_link')}.\n"
        f"9. **No Repetitive Greetings:** DO NOT include repetitive 'Hello po!' or fresh greetings in the middle of an ongoing conversation.\n"
        f"10. **Out of Scope:** If you are unsure or out of scope, politely advise them to call the owner at {biz.get('contact')}.\n"
        f"11. **AI Disclosure:** Only disclose on the VERY FIRST greeting (hello/hi) or when asked who you are: 'I am {biz.get('name')} AI support, I will assist you, and I will let the owner know what we discuss.' Do NOT repeat this disclosure in the middle of conversation.\n"
        f"13. **Food/Buddle:** Food package: {biz.get('food_package','')} Price: {biz.get('food_price','')} Buddle: {biz.get('buddle_price','')}. If asked about food, offer the package/buddle price if available, but say owner will handle food details and confirm.\n"
    )
    contents = []
    for h in history[-8:]:
        role = "user" if "Customer:" in h else "model"
        msg_text = h.split(": ", 1)[1] if ": " in h else h
        contents.append({"role": role, "parts": [{"text": msg_text}]})
    payload = {
        "contents": contents,
        "system_instruction": {"parts": [{"text": system_instruction}]}
    }
    last_status = None
    for idx, key in enumerate(keys):
        if idx > 0:
            # Smart Backoff: if previous was 429 quota, go instant (different account quota), if 503 high demand, short 0.4s
            if last_status == 429:
                print(f"[AI] Quota hit, instant switch to key {idx+1}/{len(keys)}", flush=True)
            elif last_status == 503:
                print(f"[AI] High demand, quick 0.4s before key {idx+1}/{len(keys)}", flush=True)
                time.sleep(0.4)
            else:
                print(f"[AI] Trying key {idx+1}/{len(keys)}", flush=True)
        # try 3.6 up to latest only (no old 2.0/1.5)
        for model in ["gemini-3.6-flash", "gemini-flash-latest"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                r = requests.post(url, json=payload, timeout=12)
                if r.status_code == 200:
                    res_json = r.json()
                    candidates = res_json.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            txt = parts[0].get("text", "").strip()
                            if txt:
                                print(f"[AI] key {idx+1} model {model} success", flush=True)
                                return txt
                # if 503 high demand, try next model before next key
                if r.status_code == 503:
                    print(f"[AI] key {idx+1} model {model} 503 high demand, trying next model", flush=True)
                    continue
                print(f"[AI] key {idx+1} model {model} failed {r.status_code}: {r.text[:100]}", flush=True)
                break  # for non-503, break to next key (don't try other models if 400 etc)
            except Exception as e:
                print(f"[AI ERROR] key {idx+1} model {model} {e}", flush=True)
                continue
    return None

def smart_fallback_reply(text, biz, user_name):
    t = text.lower()
    is_english = any(w in t for w in ["hi", "hello", "hey", "how", "what", "is", "are", "can", "rate", "price", "food", "location", "book", "date", "fee", "entrance", "capacity", "fit", "pax", "many"])

    if any(k in t for k in ["ilan", "kasya", "capacity", "pax", "tao", "fit", "how many"]):
        if is_english:
            return f"Good for {biz.get('capacity')} po." # Keep it strictly direct
        return f"Good for {biz.get('capacity')} po ang balsa natin."
    elif any(k in t for k in ["entrance", "fee", "bayad sa pinto", "entrancefee", "entrance fee"]):
        if is_english:
            return f"There is no separate entrance fee for the raft! Our Day Tour rate is P3,500 (7AM-4PM, good for {biz.get('capacity')}), which already includes the floating cottage, videoke, grill, and cooking gear. There is only a minimal ecological fee (around P30) at the port/municipality."
        return f"Wala po tayong hiwalay na entrance fee sa balsa! Ang meron po ay ang P3,500 Day Tour rate natin (7AM-4PM, good for {biz.get('capacity')}) na kasama na ang floating cottage, videoke, ihawan, life vest, at lutuan. May hiwalay lang po na ecological fee (mga P30) sa port o munisipyo."
    elif any(k in t for k in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]):
        display = user_name if user_name else "Mam/Sir"
        # avoid repetitive greetings in middle of conversation
        if len(t.strip()) < 12:
            if is_english:
                return f"Hello, {display}! Welcome to {biz.get('name')} in {biz.get('location')}. How can I help you today?"
            return f"Hello po {display}! Welcome sa {biz.get('name')} sa {biz.get('location')}. Ano po ang magagawa ko para sa inyo ngayon?"
        else:
            if is_english:
                return f"Yes, {display}, I hear you — how can I help with your booking?"
            return f"Opo {display}, naalala ko usapan natin — ano pa po maitutulong ko?"
    elif any(k in t for k in ["pagkain", "bili", "tindahan", "market", "palengke", "ulam", "kain", "food", "eat", "cook", "buddle", "bundle"]):
        # check if food package exists
        fp = biz.get('food_package','') or biz.get('food_price','')
        if fp and "bring your own" not in fp.lower():
            if is_english:
                return f"We have a food package/buddle available: {biz.get('food_package','')} Price: {biz.get('food_price','')} Buddle: {biz.get('buddle_price','')}. Owner will handle food details and confirm for you!"
            return f"Meron po kaming food package/buddle: {biz.get('food_package','')} Presyo: {biz.get('food_price','')} Buddle: {biz.get('buddle_price','')} — si owner na po bahala mag-confirm ng food details sa inyo!"
        
        if is_english:
            return f"You can bring your own food or buy fresh ingredients from the local market or nearby stores in Calatagan before boarding the raft. Cooking utensils and a grill are already included!"
        return f"May mga malapit na tindahan o palengke naman po sa bayan ng Calatagan kung saan kayo pwedeng mamili ng pagkain at inumin bago sumakay sa balsa."
    elif any(k in t for k in ["dec", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "petsa", "date", "araw", "available", "pwede ba", "when"]):
        if is_english:
            return f"Yes, you can inquire and check availability for that date! Our Day Tour rate is P3,500 (7AM-4PM), good for {biz.get('capacity')}. Would you like to proceed with booking?"
        return f"Yes po, available po ang mag-inquire at mag-check ng schedule para sa petsang iyan! P3,500 po ang Day Tour rate natin (7AM-4PM) good for {biz.get('capacity')}. Gusto niyo na po bang ituloy ang pagpabook?"
    elif any(k in t for k in ["magkano", "price", "rate", "pila", "balsa", "tour", "fee", "cost"]):
        if is_english:
            return f"Our Day Tour rate is P3,500 (7:00 AM - 4:00 PM). It includes the floating cottage, videoke, grill, life vests, and cooking equipment (good for {biz.get('capacity')})."
        return f"P3,500 po ang rate namin para sa Day Tour (7:00 AM - 4:00 PM). Kasama na po dyan ang floating cottage, videoke, ihawan, life vest, at lutuan (good for {biz.get('capacity')})."
    elif any(k in t for k in ["overnight", "gabi", "matulog", "sleep"]):
        if is_english:
            return f"We only offer Day Tours (7:00 AM - 4:00 PM). We do not have overnight stays."
        return f"Day Tour lang po kami (7AM hanggang 4PM) at wala pong overnight stay."
    elif any(k in t for k in ["saan", "location", "address", "map", "where"]):
        if is_english:
            return f"We are located in {biz.get('location')}. Here is our Google Maps link to guide you to our place: {biz.get('google_maps_link')}"
        return f"Kami po ay matatagpuan sa {biz.get('location')}. Narito po ang ating Google Maps link para sa inyong gabay papunta sa amin: {biz.get('google_maps_link')}"
    elif any(k in t for k in ["galing", "manggagaling", "route", "way", "paano pumunta"]):
        if is_english:
            return f"Depending on where you are coming from, you can head straight to Calatagan, Batangas. Here is the Google Maps link for your trip: {biz.get('google_maps_link')}"
        return f"Depende po kung saan kayo manggagaling, pwede kayong bumiyahe pa-Calatagan, Batangas. Eto po ang Google Maps link para sa inyong gabay: {biz.get('google_maps_link')}"
    elif any(k in t for k in ["tuloy", "sige book", "magpabook na", "kukunin na namin", "paano magbayad", "proceed", "pay"]):
        if is_english:
            return f"To lock in your schedule, a P1,000 downpayment is required via GCash ({biz.get('gcash_number')} - {biz.get('gcash_name')}). Just send the screenshot of your receipt here once paid!"
        return f"Para ma-lock po ang schedule ninyo, kailangan lang ng P1,000 downpayment sa GCash ({biz.get('gcash_number')} - {biz.get('gcash_name')}). I-send lang dito ang screenshot ng resibo pagkatapos!"
    else:
        if is_english:
            return f"Is there anything else you'd like to know? You can also contact our owner at {biz.get('contact')} for more details."
        return f"Tungkol saan po kaya ang nais niyo pang malaman? Pwede niyo pong tawagan ang aming owner sa {biz.get('contact')} para sa iba pang detalye."

def generate_reply(client, sender_id, text):
    if sender_id not in sessions:
        user_name = get_fb_user_name(client, sender_id) or "Mam/Sir"
        # ensure display is Mam/Sir + name if name exists
        if user_name and user_name != "Mam/Sir":
            user_name = f"Mam/Sir {user_name}"
        sessions[sender_id] = {"history": [], "user_name": user_name}
        # try restore from last inquiry if exists (for next-day confirm)
        try:
            from datetime import datetime as _dt
            bookings = load_bookings(client["id"]) if "load_bookings" in globals() else []
            for b in reversed(bookings):
                if b.get("customer_fb_id")==sender_id and b.get("status") in ["INQUIRY","PENDING_PAYMENT"]:
                    # restore pending info if session empty
                    sessions[sender_id]["pending_date"] = b.get("date","")
                    sessions[sender_id]["pending_pax"] = b.get("pax","")
                    sessions[sender_id]["pending_name"] = b.get("customer_name","")
                    sessions[sender_id]["pending_contact"] = b.get("contact","")
                    sessions[sender_id]["inquiry_id"] = b.get("id","")
                    sessions[sender_id]["awaiting_confirm"] = (b.get("status")=="INQUIRY")
                    print(f"[RESTORE] Restored {b['id']} for {sender_id}", flush=True)
                    break
        except: pass
    
    sess = sessions[sender_id]
    # ensure required keys exist for old sessions
    for _k in ["pending_date","pending_pax","pending_tour","pending_name","pending_contact","pending_ref","awaiting_confirm","inquiry_id"]:
        sess.setdefault(_k, "" if _k!="pending_tour" else "Day Tour")
    user_name = sess.get("user_name", "Mam/Sir")
    
    sess["history"].append(f"Customer: {text}")
    if len(sess["history"]) > 12: sess["history"] = sess["history"][-12:]
    # photo request -> notify owner and reply with available balsa photo
    low_text = text.lower()
    if any(k in low_text for k in ["itsura", "picture", "pic", "photo", "look", "balsa"] ) and any(k in low_text for k in ["available", "available", "makita", "see", "show"]):
        # notify owner
        try:
            biz_tmp = client["config"]["business_info"]
            send_owner_notif(client, {"customer_name": sess.get("pending_name") or user_name, "contact": sess.get("pending_contact") or "", "date": sess.get("pending_date") or "", "pax": sess.get("pending_pax") or "", "customer_fb_id": sender_id}, "PHOTO_REQUEST")
        except: pass
        # reply with photo of available balsa
        photo = get_available_balsa_photo(client, sess.get("pending_date",""))
        if photo:
            return f"Sure po {sess.get('pending_name') or user_name}! Here's the photo of our available balsa for {sess.get('pending_date','your date')}: {photo} 📸 I've also notified the owner to send more pics if needed!"
    # if AI senses conversation ending and no phone yet, ask for phone for owner
    if not sess.get("pending_contact") and any(k in low_text for k in ["salamat", "ok na", "confirm", "yes", "oo", "sige", "thank you", "thanks"]):
        # if we have name/date/pax but no phone, ask for phone at end
        if sess.get("pending_date") and sess.get("pending_pax") and sess.get("pending_name"):
            return f"Great! Before we end, may I have your mobile number so the owner can call you to confirm? Para matawagan kayo ni owner directly. 😊"
    # avoid repetitive hello if not start
    _is_first = len(sess["history"]) <= 2

    config = client["config"]
    biz = config["business_info"]
    api_key = config.get("ai_api_key", "")

    # Check vacation/blocked first - if blocked, reply directly without AI
    blocked_ck, reason_ck, _blk = is_date_blocked_server(client, text)
    # also try extract date from text for blocked check
    if not blocked_ck:
        import re as _re2
        for pat in [r"\d{4}-\d{1,2}-\d{1,2}", r"dec\s*\d{1,2}", r"nov\s*\d{1,2}", r"jan\s*\d{1,2}", r"feb\s*\d{1,2}", r"aug\s*\d{1,2}", r"sep\s*\d{1,2}", r"oct\s*\d{1,2}"]:
            m = _re2.search(pat, text.lower())
            if m:
                bck, rck, _ = is_date_blocked_server(client, m.group(0))
                if bck:
                    blocked_ck, reason_ck = True, rck
                    break
    if blocked_ck:
        is_vac, _ = is_vacation_active_server(client)
        if is_vac:
            until = client["config"].get("vacation_until","")
            reply_vac = f"Sorry po, sarado kami — {reason_ck} 🚫. Balik kami {until if until else 'soon'}. Gusto nyo po next open date? 😊"
            sess["history"].append(f"AI: {reply_vac}")
            save_sessions()
            return reply_vac
        else:
            reply_blk = f"Sorry po, sarado kami sa date na yan — {reason_ck} 🚫. Available po kami next open date, anong ibang date po gusto nyo? 😊"
            sess["history"].append(f"AI: {reply_blk}")
            save_sessions()
            return reply_blk

    # Check calendar for availability if asked, and add to prompt
    cal_info = ""
    if any(k in text.lower() for k in ["available", "avail", "bakante", "free", "dec ", "nov ", "jan ", "feb ", "mar ", "apr ", "may ", "jun ", "jul ", "aug ", "sep ", "oct"]):
        # extract date
        import re
        date_cand = ""
        for pat in [r"dec\s*\d{1,2}", r"nov\s*\d{1,2}", r"jan\s*\d{1,2}", r"feb\s*\d{1,2}", r"\d{4}-\d{1,2}-\d{1,2}"]:
            m=re.search(pat, text.lower())
            if m: date_cand=m.group(0); break
        if date_cand:
            avail = is_calendar_available(client, date_cand)
            if avail is True:
                cal_info = f" [Calendar: {date_cand} is AVAILABLE ({biz.get('number_of_balsas','1')} balsas, still free)] "
            elif avail is False:
                cal_info = f" [Calendar: {date_cand} is FULLY BOOKED] "
            else:
                cal_info = f" [Calendar: no data for {date_cand}, use local info] "
    # append cal info to history for AI
    if cal_info:
        sess["history"].append(f"System: {cal_info}")
    result = call_ai(api_key, biz, sess["history"], text + cal_info, user_name)
    if result:
        # strip hello if not first message (3+ history means mid-convo)
        if len(sess["history"]) > 3 and result.lower().startswith("hello"):
            result = re.sub(r"^hello[^.!]*[.!]?\s*", "", result, flags=re.I).strip()
            if result: result = result[0].upper() + result[1:] if len(result)>1 else result
        sess["history"].append(f"AI: {result}")
        save_sessions()
        return result

    fallback = smart_fallback_reply(text, biz, user_name)
    # also strip hello from fallback if not greeting intent
    if len(sess["history"]) > 3 and fallback.lower().startswith("hello"):
        # only allow hello if user actually greeted
        if not any(k in text.lower() for k in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]):
            fallback = re.sub(r"^hello[^.!]*[.!]?\s*", "", fallback, flags=re.I).strip()
            if fallback: fallback = fallback[0].upper() + fallback[1:] if len(fallback)>1 else fallback
    sess["history"].append(f"AI (Fallback): {fallback}")
    save_sessions()
    return fallback

def get_dashboard_stats_for_client(client):
    """Compute analytics for a single balsa client"""
    bookings = load_bookings(client["id"])
    biz = client["config"].get("business_info",{})
    price = int(re.sub(r"\D","", str(biz.get("price_day_amount","3500"))) or 3500)
    down = int(re.sub(r"\D","", str(biz.get("downpayment","1000"))) or 1000)
    total = len(bookings)
    confirmed = sum(1 for b in bookings if b.get("status")=="CONFIRMED")
    paid = sum(1 for b in bookings if b.get("status")=="PAID_AWAITING_CONFIRM")
    pending = sum(1 for b in bookings if b.get("status")=="PENDING_PAYMENT")
    inquiry = sum(1 for b in bookings if b.get("status")=="INQUIRY")
    cancelled = sum(1 for b in bookings if b.get("status")=="CANCELLED")
    revenue_confirmed = confirmed * price
    revenue_paid = paid * down  # downpayment only until confirmed
    revenue_total = revenue_confirmed + revenue_paid
    # peak date
    from collections import Counter
    dates = Counter(b.get("date","") for b in bookings if b.get("date") and b.get("status") not in ["CANCELLED"])
    peak_date, peak_count = dates.most_common(1)[0] if dates else ("-",0)
    # pax totals
    total_pax = 0
    for b in bookings:
        try: total_pax += int(re.search(r"\d+", str(b.get("pax","0"))).group(0))
        except: pass
    # monthly breakdown last 6 months
    monthly = Counter()
    for b in bookings:
        try:
            d = b.get("created_at","")[:7]  # YYYY-MM
            if d: monthly[d] += 1
        except: pass
    return {
        "balsa": client.get("name",""),
        "total": total, "confirmed": confirmed, "paid": paid, "pending": pending, "inquiry": inquiry, "cancelled": cancelled,
        "revenue_confirmed": revenue_confirmed, "revenue_paid_down": revenue_paid, "revenue_total": revenue_total,
        "peak_date": peak_date, "peak_count": peak_count,
        "total_pax": total_pax, "monthly": dict(monthly),
        "price": price, "down": down
    }

app = Flask(__name__, static_folder="website", static_url_path="")
app.secret_key = os.environ.get("FLASK_SECRET", "mqs_secret_2026_change_in_prod")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# === USERS / AUTH HELPERS (trial 1 day, hidden admin) — Supabase persistent, fallback to file ===
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()  # anon key
SUPABASE_TABLE = "mqs_users"

def _supabase_enabled():
    return bool(SUPABASE_URL and SUPABASE_KEY)

def _sb_headers():
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}

def load_users():
    # try Supabase first
    if _supabase_enabled():
        try:
            r = requests.get(f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?select=*", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}, timeout=8)
            if r.status_code == 200:
                data = r.json()
                # supabase stores business/vacation as jsonb, ensure they are dict
                out = []
                for u in data:
                    # normalize: supabase may return id as uuid, map to our id field
                    u["id"] = u.get("id") or u.get("user_id") or ""
                    out.append(u)
                return out
            else:
                print(f"[SB] load fail {r.status_code}: {r.text[:100]}", flush=True)
        except Exception as e:
            print(f"[SB] load error {e}", flush=True)
    if os.path.exists(USERS_PATH):
        try:
            with open(USERS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list): return data
        except: pass
    return []

def save_users(users):
    # save to file always (local backup)
    try:
        with open(USERS_PATH, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
    except: pass
    # also upsert to Supabase if enabled
    if _supabase_enabled():
        try:
            for u in users:
                # upsert by id
                payload = {
                    "id": u.get("id"),
                    "email": u.get("email","").lower(),
                    "password": u.get("password",""),
                    "name": u.get("name",""),
                    "balsa_name": u.get("balsa_name",""),
                    "gcash": u.get("gcash",""),
                    "plan": u.get("plan","trial"),
                    "created_at": u.get("created_at"),
                    "trial_end": u.get("trial_end"),
                    "business": u.get("business",{}),
                    "vacation": u.get("vacation",{}),
                    "oauth": u.get("oauth","")
                }
                r = requests.post(f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}", headers={**_sb_headers(), "Prefer": "resolution=merge-duplicates"}, json=payload, timeout=8)
                if r.status_code not in (200,201,204):
                    # try patch if post fails
                    r2 = requests.patch(f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?id=eq.{u.get('id')}", headers=_sb_headers(), json=payload, timeout=8)
                    if r2.status_code not in (200,204):
                        print(f"[SB] save fail {u.get('email')} {r.status_code}/{r2.status_code}: {r.text[:80]}", flush=True)
            print(f"[SB] saved {len(users)} users", flush=True)
        except Exception as e:
            print(f"[SB] save error {e}", flush=True)

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()
def check_pw(pw, h): return hash_pw(pw) == h
def find_user(email):
    for u in load_users():
        if u.get("email","").lower() == email.lower(): return u
    return None

def trial_info(user):
    try:
        now = datetime.now()
        # support explicit trial_end (for extends), else fallback to 1 day from created_at
        if user.get("trial_end"):
            end = datetime.fromisoformat(user["trial_end"])
        else:
            start = datetime.fromisoformat(user.get("created_at",""))
            end = start + timedelta(days=1)
        hours_left = int((end - now).total_seconds() // 3600)
        expired = now > end
        # also return days for display
        return end.strftime("%Y-%m-%d %H:%M"), hours_left, expired
    except:
        return "-", 0, False

def set_trial_end(user, days=1):
    # set trial_end to now + days (for new) or extend existing
    try:
        if user.get("trial_end"):
            end = datetime.fromisoformat(user["trial_end"])
            # if still active, extend from end, else from now
            base = end if end > datetime.now() else datetime.now()
            user["trial_end"] = (base + timedelta(days=days)).isoformat()
        else:
            start = datetime.fromisoformat(user.get("created_at",""))
            end = start + timedelta(days=1)
            base = end if end > datetime.now() else datetime.now()
            user["trial_end"] = (base + timedelta(days=days)).isoformat() if days != 1 else end.isoformat()
            # for new user with 1 day, keep created logic but also store
            if days == 1 and not user.get("trial_end"):
                user["trial_end"] = end.isoformat()
        # keep trial_days for display
        user["trial_days"] = user.get("trial_days", 1)
    except:
        user["trial_end"] = (datetime.now() + timedelta(days=days)).isoformat()

@app.route("/")
def home():
    # serve dark landing page if HTML requested, else JSON for health checks
    if "text/html" in request.headers.get("Accept",""):
        try:
            with open(os.path.join(app.static_folder, "index.html"), "r", encoding="utf-8") as f:
                return f.read(), 200, {"Content-Type": "text/html"}
        except: pass
    return jsonify({"status":"MQS ChatPilot Cloud Live with Gemini","clients":len(clients)})

@app.route("/site")
def site():
    try:
        with open(os.path.join(app.static_folder, "index.html"), "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html"}
    except Exception as e:
        return f"Site not found: {e}", 404

@app.route("/login")
def login_page():
    try:
        with open(os.path.join(app.static_folder, "login.html"), "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html"}
    except: return redirect("/")
@app.route("/register")
def register_page():
    try:
        with open(os.path.join(app.static_folder, "register.html"), "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html"}
    except: return redirect("/")
@app.route("/dashboard")
def dashboard_page():
    if not session.get("user_id"): return redirect("/login")
    try:
        with open(os.path.join(app.static_folder, "dashboard.html"), "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html"}
    except: return redirect("/")
@app.route("/mqs-admin")
def admin_page():
    # hidden admin - no nav link
    try:
        with open(os.path.join(app.static_folder, "admin.html"), "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html"}
    except: return "Admin not found", 404
@app.route("/style.css")
def style_css():
    try:
        with open(os.path.join(app.static_folder, "style.css"), "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/css"}
    except: return "", 404

@app.route("/health")
def health(): return jsonify({"ok":True})

@app.route("/admin/stats")
def admin_stats():
    token = request.headers.get("X-SYNC-TOKEN","")
    if token != os.environ.get("SYNC_TOKEN","mqs_sync_2026") and token != "mqs_sync_2026":
        return jsonify({"error":"unauthorized"}), 403
    all_stats = []
    total_rev = 0
    for c in clients:
        s = get_dashboard_stats_for_client(c)
        all_stats.append(s)
        total_rev += s["revenue_total"]
    return jsonify({"clients": all_stats, "total_revenue": total_rev, "total_clients": len(clients)})

@app.route("/admin/reminder/run", methods=["POST"])
def admin_reminder_run():
    token = request.headers.get("X-SYNC-TOKEN","")
    if token != os.environ.get("SYNC_TOKEN","mqs_sync_2026") and token != "mqs_sync_2026":
        return jsonify({"error":"unauthorized"}), 403
    try:
        run_reminders_and_reviews()
        return jsonify({"ok":True, "msg":"reminders checked"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/verify_gcash", methods=["POST"])
def admin_verify_gcash():
    token = request.headers.get("X-SYNC-TOKEN","")
    if token != os.environ.get("SYNC_TOKEN","mqs_sync_2026") and token != "mqs_sync_2026":
        return jsonify({"error":"unauthorized"}), 403
    try:
        # expects JSON with base64 image
        data = request.get_json()
        b64 = data.get("image_base64","")
        balsa_id = data.get("balsa_id","balsa_1")
        client = next((c for c in clients if c["id"]==balsa_id), clients[0] if clients else None)
        if not client: return jsonify({"error":"no client"}), 404
        import base64
        img_bytes = base64.b64decode(b64)
        biz = client["config"].get("business_info",{})
        res = verify_gcash_image(img_bytes, biz, client["config"].get("ai_api_key",""))
        return jsonify({"ok":True, "result": res})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/blocked", methods=["GET"])
def admin_blocked_get():
    token = request.headers.get("X-SYNC-TOKEN","")
    if token != os.environ.get("SYNC_TOKEN","mqs_sync_2026") and token != "mqs_sync_2026":
        return jsonify({"error":"unauthorized"}), 403
    balsa_id = request.args.get("balsa_id","balsa_1")
    client = next((c for c in clients if c["id"]==balsa_id), clients[0] if clients else None)
    if not client: return jsonify({"error":"no client"}), 404
    return jsonify({"blocked": load_blocked_dates_server(client["id"]), "vacation": {"enabled": client["config"].get("vacation_enabled",False), "until": client["config"].get("vacation_until",""), "reason": client["config"].get("vacation_reason","")}})

@app.route("/admin/blocked", methods=["POST"])
def admin_blocked_post():
    token = request.headers.get("X-SYNC-TOKEN","")
    if token != os.environ.get("SYNC_TOKEN","mqs_sync_2026") and token != "mqs_sync_2026":
        return jsonify({"error":"unauthorized"}), 403
    try:
        data = request.get_json()
        balsa_id = data.get("balsa_id","balsa_1")
        client = next((c for c in clients if c["id"]==balsa_id), None)
        if not client: return jsonify({"error":"no client"}), 404
        # vacation
        if "vacation" in data:
            vac = data["vacation"]
            client["config"]["vacation_enabled"] = bool(vac.get("enabled", False))
            client["config"]["vacation_until"] = vac.get("until","")
            client["config"]["vacation_reason"] = vac.get("reason","Vacation")
        # blocked list
        if "blocked" in data:
            p = resource_path(f"blocked_{client['id']}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data["blocked"], f, indent=4, ensure_ascii=False)
        # persist clients
        try:
            with open(CLIENTS_PATH, "w", encoding="utf-8") as f:
                json.dump(clients, f, indent=4, ensure_ascii=False)
        except: pass
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/sync", methods=["POST"])
def admin_sync():
    # allow desktop app to push clients.json
    token = request.headers.get("X-SYNC-TOKEN","")
    if token != os.environ.get("SYNC_TOKEN","mqs_sync_2026") and token != "mqs_sync_2026":
        return jsonify({"error":"unauthorized"}), 403
    try:
        data = request.get_json()
        new_clients = data.get("clients", [])
        if not new_clients or not isinstance(new_clients, list):
            return jsonify({"error":"no clients"}), 400
        global clients
        clients = new_clients
        # also fix ai keys from env
        for c in clients:
            c["config"]["ai_api_key"] = _env_key
        # save to file for persistence on Render disk
        try:
            with open(CLIENTS_PATH, "w", encoding="utf-8") as f:
                json.dump(clients, f, indent=4, ensure_ascii=False)
        except: pass
        print(f"[SYNC] Synced {len(clients)} clients from desktop", flush=True)
        return jsonify({"ok":True, "clients": len(clients)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === AUTH API (login/register/dashboard/admin) ===
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json() or {}
    email = data.get("email","").strip().lower()
    pw = data.get("password","")
    balsa = data.get("balsa_name","").strip() or "Balsa ni Trial"
    name = data.get("name","").strip() or "Owner"
    gcash = data.get("gcash","").strip()
    plan = data.get("plan","trial")
    if not email or not pw: return jsonify({"ok":False,"error":"Email at password kailangan"}), 400
    if len(pw) < 6: return jsonify({"ok":False,"error":"Password min 6 chars"}), 400
    if find_user(email): return jsonify({"ok":False,"error":"Email already registered — mag-login na"}), 400
    users = load_users()
    uid = f"U{int(time.time())%1000000:06d}"
    now = datetime.now()
    user = {"id":uid,"email":email,"password":hash_pw(pw),"name":name,"balsa_name":balsa,"gcash":gcash,"plan":plan,"created_at":now.isoformat(),"trial_end": (now + timedelta(days=1)).isoformat(),"business":{"name":balsa,"location":"Calatagan, Batangas","price_day":f"{3500} (7am-4pm)","capacity":"15 pax","inclusions":"Cottage, videoke, ihawan, life vest, lutuan","gcash_number":gcash or "09123456789","gcash_name":name,"contact":gcash or "09123456789","downpayment":"1000","google_maps_link":"","extra_info":""},"vacation":{"enabled":False,"until":"","reason":""}}
    users.append(user)
    save_users(users)
    session["user_id"] = uid
    session["email"] = email
    print(f"[AUTH] Registered {email} {balsa} {plan} trial_end {user['trial_end']}", flush=True)
    return jsonify({"ok":True})

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    email = data.get("email","").strip().lower()
    pw = data.get("password","")
    u = find_user(email)
    if not u or not check_pw(pw, u.get("password","")):
        return jsonify({"ok":False,"error":"Mali email o password"}), 401
    session["user_id"] = u["id"]
    session["email"] = u["email"]
    return jsonify({"ok":True})

@app.route("/api/oauth", methods=["POST"])
def api_oauth():
    data = request.get_json() or {}
    email = data.get("email","").strip().lower()
    provider = data.get("provider","google")
    balsa = data.get("balsa_name","Balsa ni Trial")
    if not email: return jsonify({"ok":False,"error":"Email kailangan"}), 400
    u = find_user(email)
    if not u:
        users = load_users()
        uid = f"U{int(time.time())%1000000:06d}"
        now = datetime.now()
        u = {"id":uid,"email":email,"password":hash_pw("oauth_"+provider),"name":email.split("@")[0],"balsa_name":balsa,"gcash":"","plan":"trial","created_at":now.isoformat(),"trial_end": (now + timedelta(days=1)).isoformat(),"business":{"name":balsa,"location":"Calatagan, Batangas","price_day":"3500 (7am-4pm)","capacity":"15 pax","inclusions":"Cottage, videoke, ihawan, life vest, lutuan","gcash_number":"09123456789","gcash_name":email.split("@")[0],"contact":"09123456789","downpayment":"1000","google_maps_link":"","extra_info":""},"vacation":{"enabled":False,"until":"","reason":""},"oauth":provider}
        users.append(u); save_users(users)
        print(f"[AUTH] OAuth {provider} new {email}", flush=True)
    session["user_id"] = u["id"]
    session["email"] = u["email"]
    return jsonify({"ok":True})

@app.route("/api/me")
def api_me():
    uid = session.get("user_id")
    if not uid: return jsonify({"ok":False,"error":"not logged"}), 401
    users = load_users()
    u = next((x for x in users if x["id"]==uid), None)
    if not u: return jsonify({"ok":False,"error":"not found"}), 404
    end, hours_left, expired = trial_info(u)
    return jsonify({"ok":True,"user":{"email":u["email"],"plan":u.get("plan","trial"),"balsa_name":u.get("balsa_name",""),"id":u["id"]},"business":u.get("business",{}),"vacation":u.get("vacation",{}),"trial_end":end,"trial_hours_left":hours_left,"trial_expired":expired})

@app.route("/api/save-business", methods=["POST"])
def api_save_business():
    uid = session.get("user_id")
    if not uid: return jsonify({"ok":False,"error":"not logged"}), 401
    data = request.get_json() or {}
    users = load_users()
    for u in users:
        if u["id"]==uid:
            # only update business + vacation (not email)
            for k in ["name","location","price_day","capacity","inclusions","gcash_number","gcash_name","contact","downpayment","google_maps_link","extra_info"]:
                if k in data: u["business"][k] = data[k]
            if "vacation" in data:
                u["vacation"] = data["vacation"]
            save_users(users)
            return jsonify({"ok":True})
    return jsonify({"ok":False,"error":"not found"}), 404

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok":True})

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    pw = (request.get_json() or {}).get("password","")
    expected = os.environ.get("ADMIN_PASS") or os.environ.get("SYNC_TOKEN") or "mqs_sync_2026"
    if pw == expected:
        session["is_admin"] = True
        return jsonify({"ok":True})
    return jsonify({"ok":False,"error":"Wrong admin password"}), 401

@app.route("/api/admin/users")
def api_admin_users():
    # check admin via session or token header
    if not session.get("is_admin") and request.headers.get("X-ADMIN-TOKEN") != (os.environ.get("ADMIN_PASS") or os.environ.get("SYNC_TOKEN") or "mqs_sync_2026"):
        return jsonify({"ok":False,"error":"unauthorized"}), 403
    users = load_users()
    out = []
    stats = {"trial":0,"expired":0,"paid":0}
    for u in users:
        _, hl, exp = trial_info(u)
        out.append({"id":u["id"],"email":u["email"],"balsa_name":u.get("balsa_name",""),"plan":u.get("plan","trial"),"created_at":u.get("created_at","")[:16],"trial_hours_left":hl,"trial_expired":exp})
        if u.get("plan")=="trial" and not exp: stats["trial"]+=1
        elif exp: stats["expired"]+=1
        else: stats["paid"]+=1
    return jsonify({"ok":True,"users":out,"stats":stats})

@app.route("/api/admin/extend", methods=["POST"])
def api_admin_extend():
    if not session.get("is_admin") and request.headers.get("X-ADMIN-TOKEN") != (os.environ.get("ADMIN_PASS") or os.environ.get("SYNC_TOKEN") or "mqs_sync_2026"):
        return jsonify({"ok":False,"error":"unauthorized"}), 403
    data = request.get_json() or {}
    uid = data.get("user_id"); days = int(data.get("days",7))
    users = load_users()
    for u in users:
        if u["id"]==uid:
            # extend trial_end (if expired, from now, else from current end)
            try:
                if u.get("trial_end"):
                    end = datetime.fromisoformat(u["trial_end"])
                    base = end if end > datetime.now() else datetime.now()
                    u["trial_end"] = (base + timedelta(days=days)).isoformat()
                else:
                    start = datetime.fromisoformat(u.get("created_at"))
                    end = start + timedelta(days=1)
                    base = end if end > datetime.now() else datetime.now()
                    u["trial_end"] = (base + timedelta(days=days)).isoformat()
            except:
                u["trial_end"] = (datetime.now() + timedelta(days=days)).isoformat()
            save_users(users)
            print(f"[ADMIN] Extended {u['email']} +{days}d new end {u['trial_end']}", flush=True)
            return jsonify({"ok":True, "new_end": u["trial_end"]})
    return jsonify({"ok":False,"error":"not found"}), 404

@app.route("/api/admin/delete", methods=["POST"])
def api_admin_delete():
    if not session.get("is_admin") and request.headers.get("X-ADMIN-TOKEN") != (os.environ.get("ADMIN_PASS") or os.environ.get("SYNC_TOKEN") or "mqs_sync_2026"):
        return jsonify({"ok":False,"error":"unauthorized"}), 403
    uid = (request.get_json() or {}).get("user_id")
    users = [u for u in load_users() if u["id"]!=uid]
    save_users(users)
    return jsonify({"ok":True})

@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    valid = any(token == c["config"].get("verify_token","") for c in clients)
    if mode == "subscribe" and valid: return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data: return "no data", 400
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            page_id = entry.get("id", "")
            client = get_client_by_page_id(page_id) or (clients[0] if clients else None)
            if not client: continue
            for ev in entry.get("messaging", []):
                sender = ev.get("sender", {}).get("id")
                msg = ev.get("message", {})
                text = msg.get("text", "")
                attachments = msg.get("attachments", [])
                msg_id = msg.get("mid", "")
                has_image = any(a.get("type")=="image" for a in attachments)
                if not sender: continue
                if not text and not has_image: continue
                if msg_id:
                    if msg_id in seen_message_ids: continue
                    seen_message_ids[msg_id] = time.time()
                # --- GCash Screenshot Auto-Verify ---
                if has_image:
                    try:
                        img_att = next(a for a in attachments if a.get("type")=="image")
                        img_url = img_att.get("payload",{}).get("url","")
                        if img_url:
                            print(f"[GCASH] Image received from {sender}, downloading...", flush=True)
                            img_bytes = download_fb_image(img_url, client["config"].get("page_access_token",""))
                            if img_bytes:
                                biz = client["config"].get("business_info",{})
                                res = verify_gcash_image(img_bytes, biz, client["config"].get("ai_api_key",""))
                                if res and res.get("ref"):
                                    ref = re.sub(r"\D","", str(res.get("ref","")))
                                    amt = res.get("amount","")
                                    # try match booking by sender
                                    bookings = load_bookings(client["id"])
                                    matched = None
                                    for b in reversed(bookings):
                                        if b.get("customer_fb_id")==sender and b.get("status") in ["PENDING_PAYMENT","INQUIRY"] and not b.get("gcash_ref"):
                                            matched = b
                                            break
                                    if matched:
                                        matched["gcash_ref"] = ref
                                        matched["gcash_amount"] = amt
                                        matched["gcash_verified"] = bool(res.get("confident"))
                                        matched["status"] = "PAID_AWAITING_CONFIRM"
                                        matched["paid_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        # save
                                        path = resource_path(f"bookings_{client['id']}.json")
                                        try:
                                            with open(path, "w", encoding="utf-8") as f:
                                                json.dump(bookings, f, indent=4, ensure_ascii=False)
                                            with open(BOOKINGS_PATH, "w", encoding="utf-8") as f:
                                                json.dump(bookings, f, indent=4, ensure_ascii=False)
                                        except: pass
                                        reply_img = f"Salamat po! 🙏 Na-verify ko GCash screenshot nyo — Ref: {ref} Amount: {amt}. Mark ko na as PAID, i-confirm ni owner sa system. Hintay lang 1-2hrs! 🎉"
                                        send_fb_message(client, sender, reply_img)
                                        try: send_owner_notif(client, matched, "PAID")
                                        except: pass
                                        print(f"[GCASH] Auto-verified {matched['id']} ref={ref}", flush=True)
                                        continue
                                    else:
                                        send_fb_message(client, sender, f"Salamat sa GCash screenshot! Ref: {ref} Amount: {amt} — na-receive ko, i-match ko sa booking nyo. Sabihan ko si owner.")
                                        continue
                                else:
                                    # fallback: ask for ref manually
                                    send_fb_message(client, sender, "Salamat sa screenshot! 🙏 Pakisend din ang GCash Reference Number (13 digits) para ma-verify ko agad.")
                                    continue
                    except Exception as e:
                        print(f"[GCASH] image handle error {e}", flush=True)
                try:
                    reply = generate_reply(client, sender, text or "GCash screenshot")
                    if reply: send_fb_message(client, sender, reply)
                except Exception as e:
                    print(f"[WEBHOOK] ERROR {e}", flush=True)
    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)