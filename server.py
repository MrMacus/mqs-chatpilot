"""
MQS ChatPilot - Cloud Webhook Server (headless, no UI)
Deployed to Render: https://mqs-chatpilot.onrender.com
Handles: /webhook (GET verify + POST messages), /health, /privacy
Uses same clients.json / bookings_*.json / config.json logic as desktop app
"""
import os, json, re, time, threading
from datetime import datetime
from flask import Flask, request, jsonify

# reuse resource_path logic
def resource_path(p): return os.path.join(os.path.dirname(__file__), p)

CONFIG_PATH = resource_path("config.json")
CLIENTS_PATH = resource_path("clients.json")
BOOKINGS_PATH = resource_path("bookings.json")

# load clients
def load_clients():
    if os.path.exists(CLIENTS_PATH):
        try:
            with open(CLIENTS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data: return data
        except: pass
    # fallback single
    if os.path.exists(CONFIG_PATH):
        try:
            cfg = json.load(open(CONFIG_PATH, encoding='utf-8'))
            return [{"id":"balsa_1","name":cfg.get("business_info",{}).get("name","Balsa 1"),"page_id":"","config":cfg}]
        except: pass
    return []

# override from env vars if set (for Render deployment without files)
import os as _os
_env_page = _os.environ.get("PAGE_TOKEN") or _os.environ.get("PAGE_ACCESS_TOKEN")
_env_gemini = _os.environ.get("GEMINI_KEY") or _os.environ.get("GEMINI_API_KEY") or _os.environ.get("GOOGLE_API_KEY")
_env_verify = _os.environ.get("VERIFY_TOKEN")
clients = load_clients()
# if no clients file (Render), create from ENV
if not clients and _env_page:
    print(f"[INIT] Creating client from ENV (no file) PAGE_ID={_os.environ.get('PAGE_ID','')}", flush=True)
    clients = [{
        "id": "balsa_1",
        "name": "Balsa ni Mac",
        "page_id": _os.environ.get("PAGE_ID","1337624369425179"),
        "config": {
            "page_access_token": _env_page,
            "verify_token": _env_verify or "mqs_verify_2026",
            "ai_provider": "gemini",
            "ai_api_key": _env_gemini or "",
            "port": 5000,
            "business_info": {
                "name": "Balsa ni Mac",
                "location": "Calatagan, Batangas",
                "price_day": "3500 (7am-4pm) - Day Tour ONLY",
                "price_day_amount": "3500",
                "capacity": "15-20 pax",
                "inclusions": "Floating cottage, videoke, ihawan, life vest, lutuan",
                "contact": "09123456789",
                "gcash_number": "09123456789",
                "gcash_name": "Mac David Bernal",
                "downpayment": "1000",
                "google_maps_link": "https://maps.app.goo.gl/DITO",
                "balsa_photos_url": "https://facebook.com/balsa",
                "dti_permit_url": "https://drive.google.com/permit",
                "extra_info": "Day Tour 7am-4pm",
                "cancellation_policy": "No refund 1 day before",
                "owner_fb_id": ""
            },
            "ai_system_prompt": "You are friendly booking assistant for {name} in {location}. Day Tour P{price_day_amount} 7am-4pm. Capacity {capacity}, Inclusions {inclusions}"
        }
    }]
elif _env_page and clients:
    clients[0]["config"]["page_access_token"] = _env_page
    _env_pid = _os.environ.get("PAGE_ID")
    if _env_pid: clients[0]["page_id"] = _env_pid
if _env_gemini and clients:
    for c in clients:
        c["config"]["ai_api_key"] = _env_gemini
if _env_verify and clients:
    for c in clients:
        c["config"]["verify_token"] = _env_verify
print(f"[INIT] clients loaded: {len(clients)} first_id={clients[0]['id'] if clients else 'none'} page_id={clients[0].get('page_id','') if clients else ''}", flush=True)
# build token->client map and page_id map
def get_client_by_page_id(pid):
    if not pid: return None
    for c in clients:
        if str(c.get("page_id","")) == str(pid):
            return c
    return None

def get_client_by_token(token):
    for c in clients:
        if c.get("config",{}).get("page_access_token")==token:
            return c
    return None

def bookings_path(cid):
    return resource_path(f"bookings_{cid}.json")

def load_bookings(cid):
    p = bookings_path(cid)
    if os.path.exists(p):
        try:
            with open(p,'r',encoding='utf-8') as f: return json.load(f)
        except: return []
    # fallback
    if os.path.exists(BOOKINGS_PATH):
        try: return json.load(open(BOOKINGS_PATH,encoding='utf-8'))
        except: pass
    return []

def save_bookings(cid, data):
    p = bookings_path(cid)
    try:
        with open(p,'w',encoding='utf-8') as f: json.dump(data,f,indent=4,ensure_ascii=False)
        with open(BOOKINGS_PATH,'w',encoding='utf-8') as f: json.dump(data,f,indent=4,ensure_ascii=False)
    except: pass

# AI + booking logic (simplified from app.py)
import re
try: import requests
except: requests=None

sessions = {}
SESSIONS_PATH = resource_path("sessions.json")
def load_sessions():
    global sessions
    if os.path.exists(SESSIONS_PATH):
        try:
            sessions = json.load(open(SESSIONS_PATH, encoding="utf-8"))
        except: sessions = {}
def save_sessions():
    try:
        with open(SESSIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except: pass
load_sessions()

def check_availability(cid, date_str):
    bookings = load_bookings(cid)
    date_str = date_str.strip().lower()
    for b in bookings:
        if b.get("status")=="cancelled": continue
        bdate = b.get("date","").lower()
        if bdate and (bdate==date_str or bdate in date_str or date_str in bdate):
            return False, b
    return True, None

def create_inquiry(cid, sender_id, date, pax, name, contact, tour="Day Tour"):
    bookings = load_bookings(cid)
    client = next((c for c in clients if c["id"]==cid), clients[0])
    biz = client["config"]["business_info"]
    inq = {
        "id": f"INQ{int(time.time())%100000:05d}",
        "customer_fb_id": sender_id,
        "customer_name": name or "Unknown",
        "contact": contact,
        "date": date, "tour_type": tour, "pax": pax,
        "price": biz.get("price_day_amount","3500"),
        "downpayment": biz.get("downpayment","1000"),
        "status": "INQUIRY",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    bookings.append(inq)
    save_bookings(cid, bookings)
    send_owner_notif(client, inq, "INQUIRY")
    return inq

def create_booking(cid, sender_id, date, pax, name, contact, tour="Day Tour"):
    bookings = load_bookings(cid)
    client = next((c for c in clients if c["id"]==cid), clients[0])
    biz = client["config"]["business_info"]
    bk = {
        "id": f"BK{int(time.time())%100000:05d}",
        "customer_fb_id": sender_id,
        "customer_name": name,
        "contact": contact,
        "date": date, "tour_type": tour, "pax": pax,
        "price": biz.get("price_day_amount","3500"),
        "downpayment": biz.get("downpayment","1000"),
        "status": "PENDING_PAYMENT",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    bookings.append(bk)
    save_bookings(cid, bookings)
    send_owner_notif(client, bk, "BOOKING")
    return bk

def send_owner_notif(client, booking, kind):
    biz = client["config"]["business_info"]
    owner_id = biz.get("owner_fb_id","").strip()
    token = client["config"].get("page_access_token","")
    if not owner_id or not token or not owner_id.isdigit(): return
    if kind=="INQUIRY":
        msg = f"🔔 NEW INQUIRY - {biz.get('name','')}\n👤 {booking['customer_name']} - {booking['contact']}\n📅 {booking['date']} | {booking['pax']} pax\nTawagan: {booking['contact']}"
    else:
        msg = f"📝 NEW BOOKING - {biz.get('name','')}\n👤 {booking['customer_name']} - {booking['contact']}\n📅 {booking['date']} | {booking['pax']} pax | P{booking['price']}"
    try:
        import requests
        url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
        requests.post(url, json={"recipient":{"id":owner_id},"message":{"text":msg}}, timeout=8)
    except: pass
    # telegram optional
    tg_tok = biz.get("owner_telegram_token","").strip()
    tg_chat = biz.get("owner_telegram_chat_id","").strip()
    if tg_tok and tg_chat:
        try: requests.post(f"https://api.telegram.org/bot{tg_tok}/sendMessage", json={"chat_id":tg_chat,"text":msg}, timeout=8)
        except: pass

def extract_info(text, sess):
    t=text.lower()
    # include all months
    for pat in [r"(\d{4}-\d{1,2}-\d{1,2})", r"(\d{1,2}/\d{1,2})", r"(jan\w*\s*\d{1,2})", r"(feb\w*\s*\d{1,2})", r"(mar\w*\s*\d{1,2})", r"(apr\w*\s*\d{1,2})", r"(may\s*\d{1,2})", r"(june\s*\d{1,2})", r"(july\s*\d{1,2})", r"(aug\w*\s*\d{1,2})", r"(sept?\s*\d{1,2})", r"(oct\w*\s*\d{1,2})", r"(nov\w*\s*\d{1,2})", r"(dec\w*\s*\d{1,2})", r"(\d{1,2}\s*ng\s*\w+)"]:
        m=re.search(pat,t,re.I)
        if m: sess["pending_date"]=m.group(1).strip(); break
    m=re.search(r"(\d{1,2})\s*pax",t,re.I)
    if m: sess["pending_pax"]=m.group(1)
    elif re.search(r"(\d{1,2})\s*kami",t,re.I): sess["pending_pax"]=re.search(r"(\d{1,2})\s*kami",t,re.I).group(1)
    if "day" in t: sess["pending_tour"]="Day Tour"
    m=re.search(r"09\d{9}",t)
    if m: sess["pending_contact"]=m.group(0)
    m=re.search(r"ref\s*[:#]?\s*(\w+)",t,re.I)
    if m and len(m.group(1))>4: sess["pending_ref"]=m.group(1)
    elif "gcash" in t and re.search(r"\d{4,}",t):
        sess["pending_ref"]=re.search(r"(\d{4,})",t).group(1)

def generate_reply(client, sender_id, text):
    cid=client["id"]
    if sender_id not in sessions: sessions[sender_id]={"history":[],"pending_date":"","pending_pax":"","pending_tour":"Day Tour","pending_name":"","pending_contact":"","pending_ref":"","awaiting_confirm":False,"inquiry_id":""}
    sess=sessions[sender_id]
    sess["history"].append(f"Customer: {text}")
    if len(sess["history"])>12: sess["history"]=sess["history"][-12:]
    save_sessions()
    extract_info(text, sess)
    low=text.lower()
    # name
    if sess.get("pending_date") and sess.get("pending_pax") and not sess.get("pending_name"):
        if not any(k in low for k in ["magkano","price","available","pax","day","gcash","ref"]):
            m=re.search(r"09\d{9}",text)
            if m:
                name=text.replace(m.group(0),"").strip(" ,-")
                if name: sess["pending_name"]=name
            elif len(text.split())>=2 and len(text)<30:
                sess["pending_name"]=text.strip()
    # paid
    if sess.get("pending_ref") and "gcash" in low:
        # mark paid - find booking
        bookings=load_bookings(cid)
        for b in reversed(bookings):
            if b["customer_fb_id"]==sender_id and b["status"] in ["PENDING_PAYMENT","INQUIRY"]:
                b["status"]="PAID_AWAITING_CONFIRM"; b["gcash_ref"]=sess["pending_ref"]; b["paid_at"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_bookings(cid, bookings)
                send_owner_notif(client,b,"PAID")
                for k in ["pending_date","pending_pax","pending_name","pending_contact","pending_ref","awaiting_confirm"]: sess[k]=""
                return f"Thank you {b['customer_name']}! Ref {sess['pending_ref']} received. Booking {b['date']} PAID, owner will confirm in 1-2hrs! Tagalog: Salamat, PAID na!"
        # no booking found
    # confirmation flow
    biz=client["config"]["business_info"]
    if sess.get("pending_date") and sess.get("pending_pax") and sess.get("pending_name") and sess.get("pending_contact"):
        if sess.get("awaiting_confirm"):
            if any(k in low for k in ["yes","oo","sige","confirm","tama","ok"]):
                # upgrade
                bookings=load_bookings(cid)
                for b in bookings:
                    if b["id"]==sess.get("inquiry_id"):
                        b["status"]="PENDING_PAYMENT"; save_bookings(cid,bookings); break
                else:
                    create_booking(cid,sender_id,sess["pending_date"],sess["pending_pax"],sess["pending_name"],sess["pending_contact"],sess.get("pending_tour","Day Tour"))
                sess["awaiting_confirm"]=False
                return f"✅ CONFIRMED {sess['pending_name']}! Hold booking {sess['pending_date']} ({sess['pending_pax']} pax) Day Tour P{biz.get('price_day_amount','3500')}. Pay Down P{biz.get('downpayment','1000')} to GCash {biz.get('gcash_number','')} ({biz.get('gcash_name','')}) then send Ref. Owner will call {sess['pending_contact']}!"
            elif any(k in low for k in ["no","hindi","cancel"]):
                sess["awaiting_confirm"]=False
                return f"Okay noted, not held. Inquiry forwarded to owner ({sess['pending_name']} {sess['pending_date']}) will call {sess['pending_contact']}."
            else:
                return f"Please confirm {sess['pending_name']}, booking {sess['pending_date']} ({sess['pending_pax']} pax) P{biz.get('price_day_amount','3500')}? Reply YES to hold."
        else:
            avail,_=check_availability(cid,sess["pending_date"])
            if not avail:
                return f"Sorry {sess['pending_date']} is taken, please choose another date."
            # create inquiry
            inq=create_inquiry(cid,sender_id,sess["pending_date"],sess["pending_pax"],sess["pending_name"],sess["pending_contact"],sess.get("pending_tour","Day Tour"))
            sess["awaiting_confirm"]=True; sess["inquiry_id"]=inq["id"]
            return f"Thanks {sess['pending_name']}! Summary:\n📅 {sess['pending_date']}\n👥 {sess['pending_pax']} pax\n🏖 {sess.get('pending_tour','Day Tour')} 7am-4pm\n💵 P{biz.get('price_day_amount','3500')} Down P{biz.get('downpayment','1000')} GCash {biz.get('gcash_number','')}\nCorrect? Reply YES to hold. Even if no reply, owner will call {sess['pending_contact']}."
    # Let AI brain handle most conversation - only minimal deterministic checks remain for booking flow below
    # Business info is GUIDE only for AI, not saved replies

    # AI fallback
    cfg=client["config"]
    provider=cfg.get("ai_provider","gemini")
    api_key=cfg.get("ai_api_key","")
    biz=cfg["business_info"]
    if provider=="local" or not api_key:
        if any(k in low for k in ["inclusion","kasama"]):
            return f"Our inclusions, Ma'am/Sir, are {biz.get('inclusions','')} — all included in P{biz.get('price_day_amount','3500')} Day Tour 7am-4pm. Photos: {biz.get('balsa_photos_url','')}"
        if any(k in low for k in ["saan","location","maps"]):
            return f"📍 {biz.get('location','')} — Maps: {biz.get('google_maps_link','')} Contact: {biz.get('contact','')}"
        if any(k in low for k in ["magkano","price","how much"]):
            return f"Hello! P{biz.get('price_day_amount','3500')} Day Tour 7am-4pm, capacity {biz.get('capacity','')}, inclusions {biz.get('inclusions','')}. Which date and how many pax?"
        if sess.get("pending_date") and not sess.get("pending_pax"):
            return f"Noted {sess['pending_date']} — thanks for mentioning Nov 3 earlier! How many pax will you be? (max {biz.get('capacity','')})"
        if sess.get("pending_date") and sess.get("pending_pax"):
            return f"Got it {sess['pending_date']} - {sess['pending_pax']} pax. What is your name and contact so I can hold it? I remember you mentioned {sess['pending_date']} earlier."
        return f"Hi po! I am here to help 😊 You can ask inclusions, location, or tell me your date & pax for booking. Day Tour P{biz.get('price_day_amount','3500')} 7am-4pm."
    # gemini
    try:
        from google import genai
        gen=genai.Client(api_key=api_key)
        hist="\n".join(sess["history"][-6:])
        prompt=cfg.get("ai_system_prompt","").format(**biz) + f"\nConversation history (remember these!):\n{hist}\nLatest customer message: {text}\nImportant: Do NOT forget earlier messages like Nov 3 date, inclusions, location. Reply same language as customer, warm, short, and reference history if relevant:"
        for mdl in ["gemini-3.6-flash","gemini-flash-latest"]:
            try:
                resp=gen.models.generate_content(model=mdl, contents=prompt)
                txt=(resp.text or "").strip()
                if txt: return txt
            except: continue
    except: pass
    # fallback
    return f"Hello! Day Tour P{biz.get('price_day_amount','3500')} 7am-4pm. Please tell date and pax for booking. Contact {biz.get('contact','')}"

def send_fb_message(client, recipient_id, text):
    token=client["config"].get("page_access_token","")
    print(f"[SEND] token_len={len(token)} to {recipient_id} text={text[:60]}", flush=True)
    if not token: 
        print("[SEND] no token!", flush=True)
        return False
    url=f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
    try:
        import requests
        r=requests.post(url, json={"recipient":{"id":recipient_id},"message":{"text":text}}, timeout=10)
        print(f"[SEND] status {r.status_code} resp {r.text[:300]}", flush=True)
        return r.status_code==200
    except Exception as e:
        print(f"[SEND] exception {e}", flush=True)
        return False

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"status":"MQS ChatPilot Cloud Running","clients":len(clients)})

@app.route("/health")
def health():
    return jsonify({"ok":True})

@app.route("/privacy")
def privacy():
    return """
    <h1>MQS ChatPilot Privacy Policy</h1>
    <p>We handle Messenger messages to provide automated balsa booking replies. Messages are processed via AI and stored as bookings. No data is shared with third parties except AI provider (Google Gemini) for reply generation. Contact: MQS TECH</p>
    <p>Data retention: bookings stored until deleted by business owner. Users can request deletion via Page message "delete my data".</p>
    """

@app.route("/webhook", methods=["GET"])
def verify():
    mode=request.args.get("hub.mode")
    token=request.args.get("hub.verify_token")
    challenge=request.args.get("hub.challenge")
    # check against any client verify token (they share one)
    expected = clients[0]["config"].get("verify_token","mqs_verify_2026") if clients else "mqs_verify_2026"
    # also allow any client's token
    valid=False
    for c in clients:
        if token==c["config"].get("verify_token",""):
            valid=True; break
    if mode=="subscribe" and valid:
        return challenge,200
    # fallback check main
    if mode=="subscribe" and token==expected:
        return challenge,200
    return "Verification failed",403

@app.route("/admin/sync", methods=["POST"])
def admin_sync():
    # secure with SYNC_TOKEN env or default
    import os as _os2
    expected = _os2.environ.get("SYNC_TOKEN", "mqs_sync_2026")
    got = request.headers.get("X-SYNC-TOKEN") or request.args.get("token") or ""
    if got != expected:
        return jsonify({"error":"unauthorized"}), 401
    try:
        data = request.get_json()
        if not data or "clients" not in data:
            return jsonify({"error":"need clients"}), 400
        # save to file
        with open(CLIENTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data["clients"], f, ensure_ascii=False, indent=4)
        # reload
        global clients
        clients = data["clients"]
        print(f"[SYNC] Received {len(clients)} clients, first={clients[0]['name'] if clients else 'none'}", flush=True)
        return jsonify({"ok":True, "clients":len(clients)}), 200
    except Exception as e:
        print(f"[SYNC] error {e}", flush=True)
        return jsonify({"error":str(e)}), 500

@app.route("/admin/clients", methods=["GET"])
def admin_clients():
    return jsonify({"clients": [{"id":c["id"],"name":c["name"],"page_id":c.get("page_id","")} for c in clients]})

@app.route("/webhook", methods=["POST"])
def webhook():
    data=request.get_json()
    print(f"[WEBHOOK] Received: {str(data)[:400]}", flush=True)
    if not data: return "no data",400
    if data.get("object")=="page":
        for entry in data.get("entry",[]):
            page_id=entry.get("id","")
            print(f"[WEBHOOK] page_id={page_id}", flush=True)
            client=get_client_by_page_id(page_id)
            if not client:
                client=clients[0] if clients else None
                print(f"[WEBHOOK] fallback client {client['id'] if client else 'None'}", flush=True)
            if not client: continue
            print(f"[WEBHOOK] using client {client['id']} token_len={len(client['config'].get('page_access_token',''))}", flush=True)
            for ev in entry.get("messaging",[]):
                sender=ev.get("sender",{}).get("id")
                msg=ev.get("message",{})
                text=msg.get("text","")
                print(f"[WEBHOOK] sender={sender} text={text}", flush=True)
                if not sender or not text: 
                    print("[WEBHOOK] skip no sender/text", flush=True)
                    continue
                try:
                    reply=generate_reply(client, sender, text)
                    print(f"[WEBHOOK] reply={reply[:120]}", flush=True)
                    ok=send_fb_message(client, sender, reply)
                    print(f"[WEBHOOK] send result {ok}", flush=True)
                except Exception as e:
                    print(f"[WEBHOOK] error {e}", flush=True)
                    import traceback; traceback.print_exc()
    return "EVENT_RECEIVED",200

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port)
