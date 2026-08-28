"""
MQS ChatPilot - Cloud Webhook Server for Render Deployment
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

def smart_fallback_reply(text, biz):
    t = text.lower()
    if any(k in t for k in ["magkano", "price", "rate", "pila", "balsa", "tour", "fee"]):
        return f"Hello po! Ang Day Tour rate po namin ay P{biz.get('price_day_amount','3500')} (7:00 AM - 4:00 PM). Kasama na po ang floating cottage, videoke, ihawan, life vest, at lutuan! Good for {biz.get('capacity','15-20 pax')} po siya."
    elif any(k in t for k in ["overnight", "gabi", "matulog"]):
        return f"Paumanhin po, Day Tour lang po kami (7:00 AM - 4:00 PM) at walang overnight stay. Pwede niyo po kaming tawagan sa {biz.get('contact','')} para sa iba pang detalye."
    elif any(k in t for k in ["saan", "location", "address", "map", "paano pumunta"]):
        return f"Located po kami sa {biz.get('location','Calatagan, Batangas')}. Narito po ang Google Maps link namin para madali kayong makarating: {biz.get('google_maps_link','')}"
    elif any(k in t for k in ["gcash", "payment", "downpayment", "pay", "bayad"]):
        return f"Para po sa downpayment na P{biz.get('downpayment','1000')}, maaari niyo pong i-send sa GCash:\nName: {biz.get('gcash_name','')}\nNumber: {biz.get('gcash_number','')}\n\nI-send lang po dito ang screenshot ng resibo!"
    elif any(k in t for k in ["salamat", "thank", "thanks", "ayos", "sige"]):
        return "Walang anuman po! Masaya kaming makatulong. Sabihin niyo lang po kung may kailangan pa kayong malaman o kung gustong mag-book."
    elif any(k in t for k in ["hi", "hello", "hey", "pwedeng mag tanong", "mga tanong"]):
        return f"Hello po! Welcome sa {biz.get('name','Balsa ni Mac')} sa {biz.get('location','Calatagan')}. May gusto po ba kayong malaman tungkol sa aming Day Tour?"
    else:
        # Pangkalahatang sagot na hindi paulit-ulit ang buong intro
        responses = [
            f"Nakuha ko po ang inyong mensahhe! Para sa mga booking o katanungan tungkol sa aming balsa sa {biz.get('location','Calatagan')}, maaari po kayong mag-inquire tungkol sa rate, location, o kung paano mag-downpayment.",
            f"Nasabi niyo po iyon! Ang Day Tour po namin ay nagkakahalagang P{biz.get('price_day_amount','3500')} mula 7AM hanggang 4PM. Gusto niyo po bang malaman ang mga kasama na inclusions?",
            f"Tungkol saan po kaya ang nais niyo pang malaman? Pwede niyo po kaming tanungin tungkol sa rate, capacity, o sa pag-book ng petsa."
        ]
        return random.choice(responses)

def call_ai(api_key, biz, history, text):
    return None

def generate_reply(client, sender_id, text):
    if sender_id not in sessions:
        sessions[sender_id] = {
            "history": [], "pending_date": "", "pending_pax": "",
            "pending_tour": "Day Tour", "pending_name": "", "pending_contact": "",
            "pending_ref": "", "awaiting_confirm": False, "inquiry_id": ""
        }
    sess = sessions[sender_id]
    sess["history"].append(f"Customer: {text}")
    if len(sess["history"]) > 12: sess["history"] = sess["history"][-12:]

    config = client["config"]
    biz = config["business_info"]
    api_key = config.get("ai_api_key", "")

    result = call_ai(api_key, biz, sess["history"], text)
    if result:
        sess["history"].append(f"AI: {result}")
        save_sessions()
        return result

    fallback = smart_fallback_reply(text, biz)
    sess["history"].append(f"AI (Fallback): {fallback}")
    save_sessions()
    return fallback

app = Flask(__name__)

@app.route("/")
def home(): return jsonify({"status":"MQS ChatPilot Cloud Live","clients":len(clients)})

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