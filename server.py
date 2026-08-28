"""
MQS ChatPilot - Cloud Webhook Server with Gemini AI API Rotation & Backoff Delay
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

# Multi-API Key Setup (Supports GEMINI_KEY, GEMINI_KEY_1, GEMINI_KEY_2, GEMINI_KEY_3, etc.)
def load_api_keys():
    keys = []
    env_single = os.environ.get("GEMINI_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("AI_API_KEY") or ""
    if env_single:
        for k in env_single.split(","):
            if k.strip(): keys.append(k.strip())
    
    for i in range(1, 10):
        k = os.environ.get(f"GEMINI_KEY_{i}") or os.environ.get(f"AI_API_KEY_{i}")
        if k and k.strip() and k.strip() not in keys:
            keys.append(k.strip())
            
    return keys

api_keys_pool = load_api_keys()

_env_page = os.environ.get("PAGE_TOKEN") or os.environ.get("PAGE_ACCESS_TOKEN")
_env_verify = os.environ.get("VERIFY_TOKEN")
_env_pid = os.environ.get("PAGE_ID")

clients = load_clients()
if not clients and _env_page:
    clients = [{
        "id": "balsa_1", "name": "Balsa ni Mac",
        "page_id": _env_pid or "1337624369425179",
        "config": {
            "page_access_token": _env_page,
            "verify_token": _env_verify or "mqs_verify_2026",
            "ai_api_key": api_keys_pool[0] if api_keys_pool else "",
            "port": 5000,
            "business_info": {
                "name": "Balsa ni Mac", "location": "Calatagan, Batangas",
                "price_day": "3500 (7am-4pm)", "price_day_amount": "3500",
                "capacity": "15-20 pax",
                "inclusions": "Floating cottage, videoke, ihawan, life vest, lutuan",
                "contact": "09123456789",
                "owner_name": "Mac David Bernal",
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
    if api_keys_pool:
        c["config"]["ai_api_key"] = api_keys_pool[0]

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
    if not token: return "Kaibigan"
    url = f"https://graph.facebook.com/v19.0/{sender_id}?fields=first_name&access_token={token}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get("first_name", "Kaibigan")
    except:
        pass
    return "Kaibigan"

def send_fb_message(client, recipient_id, text):
    token = client["config"].get("page_access_token","")
    if not token: return False
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
    try:
        r = requests.post(url, json={"recipient":{"id":recipient_id},"message":{"text":text}}, timeout=10)
        return r.status_code == 200
    except:
        return False

def call_ai_with_rotation(biz, history, text, user_name):
    keys = api_keys_pool if api_keys_pool else [os.environ.get("GEMINI_KEY", "")]
    if not keys or not keys[0]: return None
    
    system_instruction = (
        f"You are the friendly and cheerful chat assistant of {biz.get('name')} located in {biz.get('location')}. "
        f"The user's name is {user_name}. "
        f"Rules:\n"
        f"1. **Language Matching:** Match the language used by the customer. If they speak Tagalog/Taglish, reply in Tagalog/Taglish. If they speak English, reply in fluent English.\n"
        f"2. **Greetings:** If it's the start of the conversation or they say hi/hello, greet them properly using their name ({user_name}) and ask how you can help.\n"
        f"3. **Direct & Specific Answers (STRICT):** Sagutin LANG ang eksaktong tinatanong ng customer. HUWAG magsasama ng presyo, oras, o inclusions kung hindi naman tinatanong.\n"
        f"4. **No Entrance Fee:** Walang hiwalay na entrance fee sa balsa. Ang meron ay ang package rate na P{biz.get('price_day_amount')} para sa Day Tour (7:00 AM - 4:00 PM) na kasama na ang {biz.get('inclusions')}. May hiwalay lang na ecological fee (mga P30) sa port/munisipyo.\n"
        f"5. **Unknown / Out of Scope Inquiries (STRICT):** Kung hindi mo alam ang sagot o wala sa iyong kaalaman bilang AI (tulad ng mga espesyal na request, aso/pets, o personal na patakaran), sabihin nang direkta na hindi mo alam dahil kulang ang iyong kaalaman bilang AI, at ibigay agad ang pangalan ng owner na si {biz.get('owner_name', 'Mac David Bernal')} kasama ang kanyang contact number ({biz.get('contact')}) para matawagan nila.\n"
        f"6. **No Premature Downpayment:** DO NOT mention downpayment or GCash when they are asking about capacity, fees, rates, dates, food, parking, pets, or owner contact details. Answer their specific questions directly first.\n"
        f"7. **Booking Confirmation Only:** Only mention the P{biz.get('downpayment')} downpayment and GCash details ({biz.get('gcash_number')} - {biz.get('gcash_name')}) at the very end when they explicitly confirm they want to book.\n"
        f"8. **Day Tour Only:** Day Tour only (7:00 AM - 4:00 PM). No overnight stay.\n"
        f"9. **Location & Parking Inquiries:** Kapag tinanong ang location, ibigay ang {biz.get('location')} at Google Maps link: {biz.get('google_maps_link')}. Kapag tinanong ang tungkol sa parking, sabihing mayroon namang pwedeng maparadahan malapit sa port/babaan.\n"
        f"10. **No Repetitive Greetings:** DO NOT include repetitive 'Hello po!' or fresh greetings in the middle of an ongoing conversation.\n"
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
        if not key: continue
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={key}"
        try:
            r = requests.post(url, json=payload, timeout=8)
            if r.status_code == 200:
                res_json = r.json()
                candidates = res_json.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
            else:
                print(f"[API ROTATION] Key index {idx} failed with status {r.status_code}. Backing off...", flush=True)
                time.sleep(1.0)
        except Exception as e:
            print(f"[API ROTATION] Exception with key index {idx}: {e}. Backing off...", flush=True)
            time.sleep(1.0)
            
    return None

def smart_fallback_reply(text, biz, user_name):
    t = text.lower()
    if any(k in t for k in ["number", "owner", "may-ari", "tawagan", "call", "contact", "cp", "telepono"]):
        return f"Maaari ninyong tawagan o i-text nang direkta ang ating owner na si {biz.get('owner_name', 'Mac David Bernal')} sa numerong {biz.get('contact')} para sa iba pang katanungan."
    elif any(k in t for k in ["aso", "dog", "pet", "alaga", "pusa", "cat", "bata", "kids", "child"]):
        return f"Pasensya na po, Kaibigan, hindi ko po eksaktong alam ang patakaran ukol sa pagpapasok ng aso o pets dahil kulang po ang aking kaalaman bilang AI. Maaari niyo pong direktang tawagan o i-message ang owner na si {biz.get('owner_name', 'Mac David Bernal')} sa {biz.get('contact')} para ma-confirm kung pwede po ang inyong pet."
    elif any(k in t for k in ["parking", "parada", "kotse", "car", "sasakyan"]):
        return f"Yes po, mayroon namang pwedeng maparadahan para sa mga sasakyan malapit sa aming jump-off point o port."
    elif any(k in t for k in ["ilan", "kasya", "capacity", "pax", "tao", "fit", "how many"]):
        return f"Ang atin pong balsa ay kasya ang hanggang {biz.get('capacity')} katao, Kaibigan!"
    elif any(k in t for k in ["entrance", "fee", "bayad sa pinto", "entrancefee", "entrance fee"]):
        return f"Wala po tayong hiwalay na entrance fee sa balsa! Ang meron po ay ang P3,500 Day Tour rate natin (7AM-4PM, good for {biz.get('capacity')}) na kasama na ang floating cottage, videoke, ihawan, life vest, at lutuan. May hiwalay lang po na ecological fee (mga P30) sa port o munisipyo."
    elif any(k in t for k in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]):
        return f"Hello po, {user_name}! Welcome sa {biz.get('name')} dito sa {biz.get('location')}. Ako po ang inyong chat assistant. Paano ko po kayo matutulungan ngayon?"
    elif any(k in t for k in ["pagkain", "bili", "tindahan", "market", "palengke", "ulam", "kain", "food", "eat", "cook"]):
        return f"May mga malapit na tindahan o palengke naman po sa bayan ng Calatagan kung saan kayo pwedeng mamili ng pagkain at inumin bago sumakay sa balsa."
    elif any(k in t for k in ["dec", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "petsa", "date", "araw", "available", "pwede ba", "when"]):
        return f"Yes po, available po ang mag-inquire at mag-check ng schedule para sa petsang iyan! P3,500 po ang Day Tour rate natin (7AM-4PM) good for {biz.get('capacity')}. Gusto niyo na po bang ituloy ang pagpabook?"
    elif any(k in t for k in ["magkano", "price", "rate", "pila", "balsa", "tour", "fee", "cost"]):
        return f"P3,500 po ang rate namin para sa Day Tour (7:00 AM - 4:00 PM). Kasama na po dyan ang floating cottage, videoke, ihawan, life vest, at lutuan (good for {biz.get('capacity')})."
    elif any(k in t for k in ["overnight", "gabi", "matulog", "sleep"]):
        return f"Day Tour lang po kami (7AM hanggang 4PM) at wala pong overnight stay."
    elif any(k in t for k in ["saan", "location", "address", "map", "where"]):
        return f"Kami po ay matatagpuan sa {biz.get('location')}. Narito po ang ating Google Maps link para sa inyong gabay papunta sa amin: {biz.get('google_maps_link')}"
    elif any(k in t for k in ["galing", "manggagaling", "route", "way", "paano pumunta"]):
        return f"Depende po kung saan kayo manggagaling, pwede kayong bumiyahe pa-Calatagan, Batangas. Eto po ang Google Maps link para sa inyong gabay: {biz.get('google_maps_link')}"
    elif any(k in t for k in ["tuloy", "sige book", "magpabook na", "kukunin na namin", "paano magbayad", "proceed", "pay"]):
        return f"Para ma-lock po ang schedule ninyo, kailangan lang ng P1,000 downpayment sa GCash ({biz.get('gcash_number')} - {biz.get('gcash_name')}). I-send lang dito ang screenshot ng resibo pagkatapos!"
    else:
        return f"Paumanhin, ngunit hindi ko po alam ang detalyeng iyan dahil kulang ang aking kaalaman bilang AI. Maaari ninyong tawagan o i-text nang direkta ang ating owner na si {biz.get('owner_name', 'Mac David Bernal')} sa numerong {biz.get('contact')} para sa iba pang katanungan."

def generate_reply(client, sender_id, text):
    if sender_id not in sessions:
        user_name = get_fb_user_name(client, sender_id)
        sessions[sender_id] = {"history": [], "user_name": user_name}
    
    sess = sessions[sender_id]
    user_name = sess.get("user_name", "Kaibigan")
    
    sess["history"].append(f"Customer: {text}")
    if len(sess["history"]) > 12: sess["history"] = sess["history"][-12:]

    config = client["config"]
    biz = config["business_info"]

    result = call_ai_with_rotation(biz, sess["history"], text, user_name)
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
def home(): return jsonify({"status":"MQS ChatPilot Cloud Live with Backoff & Rotation","keys_loaded":len(api_keys_pool)})

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
