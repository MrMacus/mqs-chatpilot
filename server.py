"""
MQS ChatPilot - Cloud Webhook Server for Render Deployment
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
_env_key = os.environ.get("GEMINI_KEY") or os.environ.get("OMNI_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "sk-df1543af0a48b86d-664eae-f73acc9e"
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
        return f"Hello po! Ang Day Tour rate po namin ay P{biz.get('price_day_amount','3500')} (7:00 AM - 4:00 PM). Kasama na po ang floating cottage, videoke, ihawan, life vest, at lutuan! Good for {biz.get('capacity','15-20 pax')} po siya. Gusto niyo po ba magpa-book?"
    elif any(k in t for k in ["overnight", "gabi", "matulog"]):
        return f"Paumanhin po, Day Tour lang po kami (7:00 AM - 4:00 PM) at walang overnight. Pwede niyo po kaming tawagan sa {biz.get('contact','')} para sa iba pang detalye."
    elif any(k in t for k in ["saan", "location", "address", "map", "paano pumunta"]):
        return f"Located po kami sa {biz.get('location','Calatagan, Batangas')}. Narito po ang Google Maps link namin: {biz.get('google_maps_link','')}"
    elif any(k in t for k in ["gcash", "payment", "downpayment", "pay", "bayad"]):
        return f"Para po sa downpayment na P{biz.get('downpayment','1000')}, maaari niyo pong i-send sa GCash:\nName: {biz.get('gcash_name','')}\nNumber: {biz.get('gcash_number','')}\n\nI-send lang po dito ang screenshot ng resibo pagkatapos!"
    else:
        return f"Hello po! Welcome sa {biz.get('name','Balsa ni Mac')} sa {biz.get('location','Calatagan')}. Day tour po tayo (7AM-4PM) sa halagang P{biz.get('price_day_amount','3500')} ({biz.get('capacity','15-20 pax')}). May gusto po ba kayong itanong o gustong i-book na date?"

def call_ai(api_key, biz, history, text):
    prompt_lines = [
        f"You are a friendly, warm, human-like booking assistant for {biz.get('name','Balsa')} in {biz.get('location','Calatagan')}.",
        f"Auto-detect the customer's language and reply in the SAME language they used. Keep it natural and conversational.",
        f"BUSINESS INFO:",
        f"- Business: {biz.get('name','Balsa')}",
        f"- Location: {biz.get('location','Calatagan, Batangas')}",
        f"- Google Maps: {biz.get('google_maps_link','')}",
        f"- Day Tour ONLY 7am-4pm, NO overnight. Price: P{biz.get('price_day_amount','3500')}",
        f"- Capacity: {biz.get('capacity','15-20 pax')}",
        f"- Inclusions: {biz.get('inclusions','Floating cottage, videoke, ihawan, life vest, lutuan')}",
        f"- Contact: {biz.get('contact','09123456789')}",
        f"- GCash: {biz.get('gcash_number','')} ({biz.get('gcash_name','')})",
        f"- Downpayment: P{biz.get('downpayment','1000')}",
        f"RULES:",
        f"- Be conversational, warm, use po/opo in Tagalog.",
        f"- Do NOT invent prices. Use exact amounts above.",
        f"- If asked overnight, politely say NO.",
        f"- Keep replies SHORT (2-4 sentences max)."
    ]
    if history:
        prompt_lines.append(f"\nCONVERSATION HISTORY:")
        for h in history[-8:]: prompt_lines.append(f"  {h}")
    prompt_lines.append(f"\nLatest customer message: {text}")
    prompt = "\n".join(prompt_lines)

    # Subukan direktang tawagin ang Google Gemini API gamit ang tamang recommended models
    models_to_try = ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.0-flash"]
    for mdl in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                res_json = r.json()
                txt = res_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                if txt: return txt
        except Exception as e:
            continue
            
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
    for ev in entry.get("messaging", []): # safety fallback
        pass
    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)