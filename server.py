"""
MQS ChatPilot - Cloud Webhook Server with Gemini AI Integration
Deployed to Render: https://mqs-chatpilot.onrender.com
"""
import os, json, re, time, random
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

def get_fb_user_name(client, sender_id):
    token = client["config"].get("page_access_token", "")
    if not token: return "Mam/Sir"
    url = f"https://graph.facebook.com/v19.0/{sender_id}?fields=first_name&access_token={token}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            name = r.json().get("first_name", "").strip()
            if name: return name
    except:
        pass
    return "Mam/Sir"

def send_fb_message(client, recipient_id, text):
    token = client["config"].get("page_access_token","")
    if not token: return False
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
    try:
        r = requests.post(url, json={"recipient":{"id":recipient_id},"message":{"text":text}}, timeout=10)
        return r.status_code == 200
    except:
        return False

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
    for idx, key in enumerate(keys):
        if idx > 0:
            delay = 1.0 + (idx * 0.5)
            print(f"[AI] Smart Backoff {delay}s before trying key {idx+1}/{len(keys)}", flush=True)
            time.sleep(delay)
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
        # avoid repetitive greetings in middle of conversation
        if len(t.strip()) < 12:
            if is_english:
                return f"Hello, {user_name}! Welcome to {biz.get('name')} in {biz.get('location')}. How can I help you today?"
            return f"Hello po, {user_name}! Welcome sa {biz.get('name')} sa {biz.get('location')}. Ano po ang magagawa ko para sa inyo ngayon?"
        else:
            if is_english:
                return f"Yes, {user_name}, I hear you — how can I help with your booking?"
            return f"Opo {user_name}, naalala ko usapan natin — ano pa po maitutulong ko?"
    elif any(k in t for k in ["pagkain", "bili", "tindahan", "market", "palengke", "ulam", "kain", "food", "eat", "cook"]):
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
        user_name = get_fb_user_name(client, sender_id)
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
    # avoid repetitive hello if not start
    _is_first = len(sess["history"]) <= 2

    config = client["config"]
    biz = config["business_info"]
    api_key = config.get("ai_api_key", "")

    result = call_ai(api_key, biz, sess["history"], text, user_name)
    if result:
        sess["history"].append(f"AI: {result}")
        save_sessions()
        return result

    fallback = smart_fallback_reply(text, biz, user_name)
    sess["history"].append(f"AI (Fallback): {fallback}")
    save_sessions()
    return fallback

app = Flask(__name__)

@app.route("/")
def home(): return jsonify({"status":"MQS ChatPilot Cloud Live with Gemini","clients":len(clients)})

@app.route("/health")
def health(): return jsonify({"ok":True})

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
                msg_id = msg.get("mid", "")
                if not sender or not text: continue
                if msg_id:
                    if msg_id in seen_message_ids: continue
                    seen_message_ids[msg_id] = time.time()
                try:
                    reply = generate_reply(client, sender, text)
                    if reply: send_fb_message(client, sender, reply)
                except Exception as e:
                    print(f"[WEBHOOK] ERROR {e}", flush=True)
    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)