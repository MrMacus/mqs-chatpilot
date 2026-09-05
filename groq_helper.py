# groq_helper.py — MQS ChatPilot
# Groq 10-Key Rotation (llama-3.3-70b-versatile) + Gemini Fallback + Summary/Sentiment
import os
import time
import re
import json
from typing import List, Dict, Optional

def load_groq_keys() -> List[str]:
    keys = []
    main = os.environ.get("GROQ_API_KEY", "").strip()
    if main:
        keys.extend([k.strip() for k in main.split(",") if k.strip()])
    for i in range(1, 11):
        k = os.environ.get(f"GROQ_API_KEY_{i}", "").strip()
        if k and k not in keys:
            keys.append(k)
    for v in [os.environ.get("GROQ_KEY", ""), os.environ.get("GROQ_API_KEYS", "")]:
        if v:
            for k in v.split(","):
                k=k.strip()
                if k and k not in keys:
                    keys.append(k)
    return keys[:10]

# Free-tier groq models (Enterprise llama-3.3-70b needs paid, so use OSS)
GROQ_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b", "llama-3.1-8b-instant"]
GROQ_MODEL = GROQ_MODELS[0]
GEMINI_MODEL = "gemini-2.0-flash"

def call_groq_with_fallback(
    messages: List[Dict],
    groq_keys: Optional[List[str]] = None,
    gemini_key: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 500
) -> Optional[str]:
    if groq_keys is None:
        groq_keys = load_groq_keys()
    last_error = None
    for idx, key in enumerate(groq_keys):
        # try each model for this key before switching key (404 model not found → try next model)
        for mdl in GROQ_MODELS:
            try:
                from groq import Groq
                client = Groq(api_key=key)
                if idx > 0 and "429" in str(last_error or ""):
                    print(f"[GROQ] Quota hit, instant switch key {idx+1}/{len(groq_keys)}", flush=True)
                elif idx > 0 and "503" in str(last_error or ""):
                    time.sleep(0.4)
                resp = client.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                text = resp.choices[0].message.content.strip()
                if text:
                    print(f"[GROQ] key {idx+1} model {mdl} success", flush=True)
                    return text
            except Exception as e:
                msg = str(e)
                last_error = msg
                if "404" in msg and "does not exist" in msg:
                    print(f"[GROQ] key {idx+1} model {mdl} 404 → try next model", flush=True)
                    continue  # try next model same key
                if "429" in msg or "RateLimit" in msg or "RESOURCE_EXHAUSTED" in msg or "rate_limit" in msg.lower():
                    print(f"[GROQ] key {idx+1} 429 RateLimit → next key: {msg[:120]}", flush=True)
                    break  # break model loop, switch key
                elif "503" in msg or "ServiceUnavailable" in msg:
                    print(f"[GROQ] key {idx+1} 503 → next key", flush=True)
                    break
                else:
                    print(f"[GROQ] key {idx+1} model {mdl} error: {msg[:150]}", flush=True)
                    if mdl != GROQ_MODELS[-1]:
                        continue
                    break
        # if all models failed for this key, continue to next key
        continue
    if gemini_key is None:
        gemini_key = os.environ.get("GEMINI_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        if "," in gemini_key:
            gemini_key = gemini_key.split(",")[0].strip()
    if gemini_key:
        print(f"[GROQ] Ubos 10 keys, lipat GEMINI fallback...", flush=True)
        try:
            try:
                from google import genai
                client = genai.Client(api_key=gemini_key)
                prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
                resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
                if resp.text:
                    print(f"[GEMINI] fallback success ({GEMINI_MODEL})", flush=True)
                    return resp.text.strip()
            except Exception as e1:
                print(f"[GEMINI] new SDK fail: {e1}", flush=True)
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel(GEMINI_MODEL)
                prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
                resp = model.generate_content(prompt)
                if resp.text:
                    return resp.text.strip()
        except Exception as e:
            print(f"[GEMINI] fallback fail: {e}", flush=True)
    print("[AI] Lahat Groq + Gemini failed — fallback template", flush=True)
    return None

def summarize_conversation(
    chat_history: List[str],
    groq_keys: Optional[List[str]] = None,
    gemini_key: Optional[str] = None
) -> Dict[str, str]:
    if groq_keys is None:
        groq_keys = load_groq_keys()
    history_text = "\n".join(chat_history[-20:])
    system_prompt = """Ikaw ay analyst para sa BALSA RENTAL at TOURISM sa Calatagan, Batangas.
Output dapat VALID JSON lang:
{
  "summary": "1-2 pangungusap sa TAGALOG kung anong petsa gusto mag-book, ilang tao (pax), at anong klaseng balsa (Day Tour 7am-4pm, etc.)",
  "sentiment": "Hot Booking | Pending Date | Inquiries lang",
  "action": "Ano dapat gawin ng balsa operator/coordinator"
}
Rules:
- summary: Tagalog, may petsa+pax+balsa type kung meron
- sentiment: HOT BOOKING = may pax+petsa+name/contact at gustong mag-confirm/magbayad, PENDING DATE = nagtatanong ng availability/petsa pa lang, INQUIRIES LANG = tanong ng price/inclusions/location
- action: specific, Hal: I-check ang availability ng balsa sa Aug 30, Kumpirmahin ang downpayment na P1000 sa GCash
Chat History:
""" + history_text + "\n\nIlabas JSON lang:"
    messages = [
        {"role": "system", "content": "Ikaw ay balsa rental analyst. Output JSON lang."},
        {"role": "user", "content": system_prompt}
    ]
    raw = call_groq_with_fallback(messages, groq_keys=groq_keys, gemini_key=gemini_key, temperature=0.3, max_tokens=400)
    if raw:
        try:
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                data = json.loads(m.group(0))
                return {
                    "summary": data.get("summary", "").strip(),
                    "sentiment": data.get("sentiment", "Inquiries lang").strip(),
                    "action": data.get("action", "").strip(),
                    "raw": raw
                }
        except Exception as e:
            print(f"[SUMMARY] JSON parse fail: {e} raw={raw[:200]}", flush=True)
    return {
        "summary": "Nag-inquire ang customer tungkol sa balsa, hindi pa kumpleto ang petsa/pax.",
        "sentiment": "Inquiries lang",
        "action": "Tawagan o i-follow up ang customer para sa petsa at bilang ng tao.",
        "raw": raw or ""
    }
