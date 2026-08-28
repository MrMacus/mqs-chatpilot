"""
MQS ChatPilot - Cloud Webhook Server (headless, no UI)
Deployed to Render: https://mqs-chatpilot.onrender.com
"""
import os, json, re, time
from datetime import datetime
from flask import Flask, request, jsonify
import requests

def resource_path(p): return os.path.join(os.path.dirname(__file__), p)

CONFIG_PATH = resource_path("config.json")
CLIENTS_PATH = resource_path("clients.json")
BOOKINGS_PATH = resource_path("bookings.json")
SESSIONS_PATH = resource_path("sessions.json")

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
_env_gemini = os.environ.get("GEMINI_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
_env_verify = os.environ.get("VERIFY_TOKEN")
_env_pid = os.environ.get("PAGE_ID")

clients = load_clients()
if not clients and _env_page:
    print(f"[INIT] Creating from ENV PAGE_ID={_env_pid}", flush=True)
    clients = [{
        "id": "balsa_1", "name": "Balsa ni Mac",
        "page_id": _env_pid or "1337624369425179",
        "config": {
            "page_access_token": _env_page,
            "verify_token": _env_verify or "mqs_verify_2026",
            "ai_provider": "gemini",
            "ai_api_key": _env_gemini or "",
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
if _env_gemini:
    for c in clients: c["config"]["ai_api_key"] = _env_gemini
if _env_verify:
    for c in clients: c["config"]["verify_token"] = _env_verify

print(f"[INIT] clients={len(clients)} first_token_len={len(clients[0]['config'].get('page_access_token','')) if clients else 0} gemini_key_len={len(clients[0]['config'].get('ai_api_key','')) if clients else 0}", flush=True)

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

def bookings_path(cid): return resource_path(f"bookings_{cid}.json")
def load_bookings(cid):
    p = bookings_path(cid)
    if os.path.exists(p):
        try:
            with open(p,'r',encoding='utf-8') as f: return json.load(f)
        except: return []
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
        "customer_fb_id": sender_id, "customer_name": name or "Unknown",
        "contact": contact, "date": date, "tour_type": tour, "pax": pax,
        "price": biz.get("price_day_amount","3500"),
        "downpayment": biz.get("downpayment","1000"),
        "status": "INQUIRY", "gcash_ref": "",
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
        "customer_fb_id": sender_id, "customer_name": name,
        "contact": contact, "date": date, "tour_type": tour, "pax": pax,
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
        msg = f"NEW INQUIRY - {biz.get('name','')}\n{booking['customer_name']} - {booking['contact']}\n{booking['date']} | {booking['pax']} pax\nTawagan: {booking['contact']}"
    else:
        msg = f"NEW BOOKING - {biz.get('name','')}\n{booking['customer_name']} - {booking['contact']}\n{booking['date']} | {booking['pax']} pax | P{booking['price']}"
    try:
        url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
        requests.post(url, json={"recipient":{"id":owner_id},"message":{"text":msg}}, timeout=8)
    except: pass
    tg_tok = biz.get("owner_telegram_token","").strip()
    tg_chat = biz.get("owner_telegram_chat_id","").strip()
    if tg_tok and tg_chat:
        try: requests.post(f"https://api.telegram.org/bot{tg_tok}/sendMessage", json={"chat_id":tg_chat,"text":msg}, timeout=8)
        except: pass

def send_fb_message(client, recipient_id, text):
    token = client["config"].get("page_access_token","")
    print(f"[SEND] to={recipient_id} token_len={len(token)} text={text[:80]}", flush=True)
    if not token: print("[SEND] NO TOKEN!", flush=True); return False
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
    try:
        r = requests.post(url, json={"recipient":{"id":recipient_id},"message":{"text":text}}, timeout=10)
        print(f"[SEND] status={r.status_code} resp={r.text[:200]}", flush=True)
        return r.status_code == 200
    except Exception as e:
        print(f"[SEND] error {e}", flush=True)
        return False

def call_gemini(api_key, biz, history, text, extra_context=""):
    if not api_key:
        print("[GEMINI] no api_key!", flush=True)
        return None
    prompt_lines = [
        f"You are a friendly, warm, human-like booking assistant for {biz.get('name','Balsa')} in {biz.get('location','Calatagan')}.",
        f"Auto-detect the customer's language and reply in the SAME language they used. Keep it natural and conversational - like a real person, not a robot.",
        f"",
        f"BUSINESS INFO (use as reference, not script):",
        f"- Business: {biz.get('name','Balsa')}",
        f"- Location: {biz.get('location','Calatagan, Batangas')}",
        f"- Google Maps: {biz.get('google_maps_link','')}",
        f"- Day Tour ONLY 7am-4pm, NO overnight. Price: P{biz.get('price_day_amount','3500')}",
        f"- Capacity: {biz.get('capacity','15-20 pax')}",
        f"- Inclusions: {biz.get('inclusions','Floating cottage, videoke, ihawan, life vest, lutuan')}",
        f"- Contact: {biz.get('contact','09123456789')}",
        f"- GCash: {biz.get('gcash_number','')} ({biz.get('gcash_name','')})",
        f"- Downpayment: P{biz.get('downpayment','1000')}",
        f"- DTI Permit: {biz.get('dti_permit_url','')}",
        f"- Photos: {biz.get('balsa_photos_url','')}",
        f"- Cancellation: {biz.get('cancellation_policy','No refund if cancel 1 day before')}",
        f"",
        f"RULES:",
        f"- Be conversational, warm, use po/opo in Tagalog.",
        f"- Do NOT invent prices. Use exact amounts above.",
        f"- If asked overnight, politely say NO.",
        f"- If you don't know or it's complex, say: 'Tawag nyo na lang kay owner sa {biz.get('contact','')}'",
        f"- If customer mentions a date/pax/name/contact for booking, acknowledge it naturally and guide them.",
        f"- NEVER give the same reply twice. Vary your responses.",
        f"- Keep replies SHORT (2-4 sentences max)."
    ]
    if extra_context:
        prompt_lines.append(f"\nSYSTEM NOTE / CURRENT STATUS: {extra_context}")

    if history:
        prompt_lines.append(f"\nCONVERSATION HISTORY (remember these!):")
        for h in history[-8:]:
            prompt_lines.append(f"  {h}")
    prompt_lines.append(f"\nLatest customer message: {text}")
    prompt_lines.append(f"\nReply in the customer's language, warm and short:")

    prompt = "\n".join(prompt_lines)
    try:
        from google import genai
        gen = genai.Client(api_key=api_key)
        # Updated stable models list
        for mdl in ["gemini-2.0-flash", "gemini-flash", "gemini-pro"]:
            try:
                resp = gen.models.generate_content(model=mdl, contents=prompt)
                txt = (resp.text or "").strip()
                if txt:
                    print(f"[GEMINI] {mdl} OK: {txt[:100]}", flush=True)
                    return txt
            except Exception as ge:
                print(f"[GEMINI] {mdl} FAIL: {str(ge)[:120]}", flush=True)
                continue
    except Exception as e:
        print(f"[GEMINI] import fail: {e}", flush=True)
    return None

def extract_booking_info(text, sess):
    t = text.lower()
    for pat in [r"(\d{4}-\d{1,2}-\d{1,2})", r"(\d{1,2}/\d{1,2})",
                r"(jan\w*\s*\d{1,2})", r"(feb\w*\s*\d{1,2})", r"(mar\w*\s*\d{1,2})",
                r"(apr\w*\s*\d{1,2})", r"(may\s*\d{1,2})", r"(june?\s*\d{1,2})",
                r"(july?\s*\d{1,2})", r"(aug\w*\s*\d{1,2})", r"(sept?\s*\d{1,2})",
                r"(oct\w*\s*\d{1,2})", r"(nov\w*\s*\d{1,2})", r"(dec\w*\s*\d{1,2})"]:
        m = re.search(pat, t, re.I)
        if m: sess["pending_date"] = m.group(1).strip(); break
    
    m = re.search(r"(\d{1,2})\s*pax", t, re.I)
    if m: sess["pending_pax"] = m.group(1)
    elif re.search(r"(\d{1,2})\s*kami", t, re.I):
        sess["pending_pax"] = re.search(r"(\d{1,2})\s*kami", t, re.I).group(1)

    if "day" in t: sess["pending_tour"] = "Day Tour"

    m = re.search(r"09\d{9}", t)
    if m: sess["pending_contact"] = m.group(0)

    m = re.search(r"ref\s*[:#]?\s*(\w+)", t, re.I)
    if m and len(m.group(1)) > 4: sess["pending_ref"] = m.group(1)
    elif "gcash" in t and re.search(r"\d{4,}", t):
        sess["pending_ref"] = re.search(r"(\d{4,})", t).group(1)

    if sess.get("pending_date") and sess.get("pending_pax") and not sess.get("pending_name"):
        if not any(k in t for k in ["magkano","price","available","pax","day","gcash","ref","hello","hi"]):
            m = re.search(r"09\d{9}", text)
            if m:
                name = text.replace(m.group(0), "").strip(" ,-")
                if name: sess["pending_name"] = name
            elif 2 <= len(text.split()) <= 4 and len(text) < 30 and not re.search(r"\d{2,}", text):
                sess["pending_name"] = text.strip()

def generate_reply(client, sender_id, text):
    cid = client["id"]
    if sender_id not in sessions:
        sessions[sender_id] = {
            "history": [], "pending_date": "", "pending_pax": "",
            "pending_tour": "Day Tour", "pending_name": "", "pending_contact": "",
            "pending_ref": "", "awaiting_confirm": False, "inquiry_id": ""
        }
    sess = sessions[sender_id]
    sess["history"].append(f"Customer: {text}")
    if len(sess["history"]) > 12:
        sess["history"] = sess["history"][-12:]

    extract_booking_info(text, sess)
    low = text.lower().strip()
    biz = client["config"]["business_info"]
    api_key = client["config"].get("ai_api_key", "")
    extra_context = ""

    # --- GCash ref received ---
    if sess.get("pending_ref") and "gcash" in low:
        bookings = load_bookings(cid)
        for b in reversed(bookings):
            if b["customer_fb_id"] == sender_id and b["status"] in ["PENDING_PAYMENT", "INQUIRY"]:
                b["status"] = "PAID_AWAITING_CONFIRM"
                b["gcash_ref"] = sess["pending_ref"]
                b["paid_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_bookings(cid, bookings)
                send_owner_notif(client, b, "PAID")
                extra_context = f"The customer has provided a GCash reference number ({sess['pending_ref']}). Acknowledge receipt warmly, tell them it is verified/checked, and thank them."
                for k in ["pending_ref"]: sess[k] = ""
                break

    # --- Confirmation flow ---
    if sess.get("pending_date") and sess.get("pending_pax") and sess.get("pending_name") and sess.get("pending_contact"):
        if sess.get("awaiting_confirm"):
            if any(k in low for k in ["yes","oo","sige","confirm","tama","ok na","go","yess","opo"]):
                for b in load_bookings(cid):
                    if b["id"] == sess.get("inquiry_id"):
                        b["status"] = "PENDING_PAYMENT"
                        save_bookings(cid, load_bookings(cid))
                        break
                else:
                    create_booking(cid, sender_id, sess["pending_date"], sess["pending_pax"], sess["pending_name"], sess["pending_contact"], sess.get("pending_tour","Day Tour"))
                sess["awaiting_confirm"] = False
                extra_context = "The customer confirmed the booking details. Instruct them to send the P1000 downpayment via GCash to complete the reservation."
            elif any(k in low for k in ["no","hindi","cancel","wag","ayaw"]):
                sess["awaiting_confirm"] = False
                for k in ["pending_date","pending_pax","pending_name","pending_contact"]: sess[k] = ""
                extra_context = "The customer cancelled the booking details. Ask how else you can help them."
        else:
            avail, taken = check_availability(cid, sess["pending_date"])
            if not avail:
                extra_context = f"The date {sess['pending_date']} is already fully booked or taken. Politely inform the customer and ask them to pick another date."
                sess["pending_date"] = ""
            else:
                inq = create_inquiry(cid, sender_id, sess["pending_date"], sess["pending_pax"], sess["pending_name"], sess["pending_contact"], sess.get("pending_tour","Day Tour"))
                sess["awaiting_confirm"] = True
                sess["inquiry_id"] = inq["id"]
                extra_context = f"We have collected complete booking info: Date: {sess['pending_date']}, Pax: {sess['pending_pax']}, Name: {sess['pending_name']}, Contact: {sess['pending_contact']}. Ask the customer to review and confirm if these details are correct."

    save_sessions()

    # --- GEMINI handles ALL conversation with context ---
    result = call_gemini(api_key, biz, sess["history"], text, extra_context)
    if result:
        sess["history"].append(f"AI: {result}")
        if len(sess["history"]) > 12: sess["history"] = sess["history"][-12:]
        save_sessions()
        return result

    return f"Hello! Paumanhin, medyo nahirapan ako sa sagot. Pwede mo bang ulitin o tawagan kami sa {biz.get('contact','')}?"

app = Flask(__name__)

@app.route("/")
def home(): return jsonify({"status":"MQS ChatPilot Live","clients":len(clients)})

@app.route("/health")
def health(): return jsonify({"ok":True})

@app.route("/privacy")
def privacy():
    return """<h1>MQS ChatPilot Privacy Policy</h1>
    <p>We handle Messenger messages to provide automated balsa booking replies. Messages are processed via AI and stored as bookings. No data is shared with third parties except AI provider (Google Gemini) for reply generation. Contact: MQS TECH</p>"""

@app.route("/admin/sync", methods=["POST"])
def admin_sync():
    expected = os.environ.get("SYNC_TOKEN", "mqs_sync_2026")
    got = request.headers.get("X-SYNC-TOKEN") or request.args.get("token") or ""
    if got != expected:
        return jsonify({"error":"unauthorized"}), 401
    try:
        data = request.get_json()
        if not data or "clients" not in data:
            return jsonify({"error":"need clients"}), 400
        with open(CLIENTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data["clients"], f, ensure_ascii=False, indent=4)
        global clients
        clients = data["clients"]
        print(f"[SYNC] Received {len(clients)} clients", flush=True)
        return jsonify({"ok":True, "clients":len(clients)}), 200
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/admin/clients", methods=["GET"])
def admin_clients():
    return jsonify({"clients":[{"id":c["id"],"name":c["name"],"page_id":c.get("page_id","")} for c in clients]})

@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    valid = any(token == c["config"].get("verify_token","") for c in clients)
    if mode == "subscribe" and valid:
        return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data: return "no data", 400
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            page_id = entry.get("id", "")
            client = get_client_by_page_id(page_id) or (clients[0] if clients else None)
            if not client:
                print(f"[WEBHOOK] No client for page_id={page_id}", flush=True)
                continue
            for ev in entry.get("messaging", []):
                sender = ev.get("sender", {}).get("id")
                msg = ev.get("message", {})
                text = msg.get("text", "")
                msg_id = msg.get("mid", "")
                
                if not sender or not text: continue
                
                # Deduplication check para iwas doble/loop reply
                if msg_id:
                    if msg_id in seen_message_ids:
                        print(f"[WEBHOOK] Duplicate message ignored: {msg_id}", flush=True)
                        continue
                    seen_message_ids[msg_id] = time.time()
                    now = time.time()
                    for mid in list(seen_message_ids.keys()):
                        if now - seen_message_ids[mid] > 60:
                            del seen_message_ids[mid]

                print(f"[WEBHOOK] page={page_id} sender={sender} text={text[:60]}", flush=True)
                try:
                    reply = generate_reply(client, sender, text)
                    if reply:
                        send_fb_message(client, sender, reply)
                except Exception as e:
                    print(f"[WEBHOOK] ERROR {e}", flush=True)
                    import traceback; traceback.print_exc()
    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
```[cite: 10]