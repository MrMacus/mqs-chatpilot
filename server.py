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
_env_key = "sk-df1543af0a48b86d-664eae-f73acc9e"
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

def send_fb_message(client, recipient_id, text):
    token = client["config"].get("page_access_token","")
    if not token: return False
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
    try:
        r = requests.post(url, json={"recipient":{"id":recipient_id},"message":{"text":text}}, timeout=10)
        return r.status_code == 200
    except:
        return False

def call_ai(api_key, biz, history, text):
    if not api_key: return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    system_instruction = (
        f"Ikaw ang friendly at masayahing chat assistant ng {biz.get('name')} na matatagpuan sa {biz.get('location')}. "
        f"Ang Day Tour rate ay P{biz.get('price_day_amount')} (7:00 AM - 4:00 PM), good for {biz.get('capacity')}. "
        f"Kasama rito ang: {biz.get('inclusions')}. "
        f"Wala kayong overnight stay, Day Tour lang po. "
        f"Para sa booking at downpayment, kailangan ng P{biz.get('downpayment')} sa GCash (Name: {biz.get('gcash_name')}, Number: {biz.get('gcash_number')}). "
        f"Umusap ka nang natural, parang totoong tao na palakaibigan at taga-Batangas. Huwag maging paulit-ulit o robotic ang mga sagot. Mag-iba-iba ka ng phrasing sa bawat reply para hindi nakakaumay."
    )
    
    contents = []
    for h in history[-6:]:
        role = "user" if "Customer:" in h else "model"
        msg_text = h.split(": ", 1)[1] if ": " in h else h
        contents.append({"role": role, "parts": [{"text": msg_text}]})
    
    payload = {
        "contents": contents,
        "system_instruction": {"parts": [{"text": system_instruction}]}
    }
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            res_json = r.json()
            candidates = res_json.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "").strip()
    except Exception as e:
        print(f"[AI ERROR] {e}", flush=True)
    return None

def smart_fallback_reply(text, biz):
    t = text.lower()
    if any(k in t for k in ["dec", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "petsa", "date", "araw", "available", "pwede ba", "magpabook", "book"]):
        return f"Yes po, available po mag-book sa gusto nyong date! P3,500 po ang Day Tour natin (7AM-4PM). Kailangan lang po ng P1,000 downpayment via GCash ({biz.get('gcash_number')} - {biz.get('gcash_name')}) para ma-lock po natin ang schedule ninyo."
    elif any(k in t for k in ["magkano", "price", "rate", "pila", "balsa", "tour", "fee"]):
        return f"P3,500 po ang rate namin para sa Day Tour (7:00 AM - 4:00 PM). Sulit na sulit dahil kasama na dyan ang floating cottage, videoke, ihawan, life vest, at lutuan! Pwedeng-pwede sa tropa o pamilya (good for {biz.get('capacity')})."
    elif any(k in t for k in ["overnight", "gabi", "matulog"]):
        return f"Ay sorry po, hanggang Day Tour lang po talaga kami (7AM hanggang 4PM) at wala pong overnight stay."
    elif any(k in t for k in ["saan", "location", "address", "map", "paano pumunta"]):
        return f"Sa {biz.get('location')} po kami nakaposisyon. Eto po ang Google Maps link para mas madali kayong makapunta: {biz.get('google_maps_link')}"
    elif any(k in t for k in ["gcash", "payment", "downpayment", "pay", "bayad"]):
        return f"Eto po ang GCash details para sa P1,000 downpayment:\n\nName: {biz.get('gcash_name')}\nNumber: {biz.get('gcash_number')}\n\nI-send lang po dito ang screenshot ng resibo pagkatapos magbayad!"
    else:
        return f"Hello po! Tungkol saan po kaya ang gusto ninyong malaman sa aming balsa sa {biz.get('location')}? Pwede po kayong magtanong tungkol sa rates, inclusions, o kung gusto ninyong mag-reserve ng petsa."

def generate_reply(client, sender_id, text):
    if sender_id not in sessions:
        sessions[sender_id] = {"history": []}
    sess = sessions[sender_id]
    sess["history"].append(f"Customer: {text}")
    if len(sess["history"]) > 12: sess["history"] = sess["history"][-12:]

    config = client["config"]
    biz = config["business_info"]
    api_key = config.get("ai_api_key", "")

    # Subukan munang gamitin si Gemini AI para sa natural na sagot
    result = call_ai(api_key, biz, sess["history"], text)
    if result:
        sess["history"].append(f"AI: {result}")
        save_sessions()
        return result

    # Fallback kung sakaling magka-issue ang API connection
    fallback = smart_fallback_reply(text, biz)
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