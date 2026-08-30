import os
import sys
import json
import re
import threading
import time
from datetime import datetime
import urllib.request
import urllib.parse
import webbrowser
from tkinter import messagebox

try:
    import customtkinter as ctk
except ImportError:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Missing Module", "CustomTkinter required!\nRun: pip install customtkinter")
    sys.exit()

try:
    from flask import Flask, request as flask_request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def resource_path(relative_path):
    try:
        if getattr(sys, "frozen", False):
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base_dir = os.path.abspath(".")
    return os.path.join(base_dir, relative_path)

CONFIG_PATH = resource_path("config.json")
BOOKINGS_PATH = resource_path("bookings.json")
CLIENTS_PATH = resource_path("clients.json")

DEFAULT_CONFIG = {
    "page_access_token": "",
    "verify_token": "mqs_verify_2026",
    "ai_provider": "gemini",
    "ai_api_key": "",
    "auto_reply_enabled": True,
    "vacation_enabled": False,
    "vacation_until": "",
    "vacation_reason": "Vacation",
    "port": 5000,
    "business_info": {
        "name": "Balsa ni Juan - Calatagan",
        "location": "Calatagan, Batangas",
        "price_day": "3500 (7am-4pm) - Day Tour ONLY",
        "price_day_amount": "3500",
        "price_night": "WALANG OVERNIGHT - Day Tour lang 7am-4pm",
        "price_night_amount": "4500",
        "price_22hrs": "WALANG 22hrs",
        "capacity": "15-20 pax",
        "inclusions": "Floating cottage, videoke, ihawan, life vest, lutuan",
        "contact": "09123456789",
        "contact_owner": "09123456789",
        "gcash_number": "09123456789",
        "gcash_name": "Juan Dela Cruz",
        "downpayment": "1000",
        "extra_info": "Day Tour ONLY 7am-4pm. Walang overnight. Free parking, may tindahan sa tabing dagat.",
        "google_maps_link": "https://maps.app.goo.gl/EXAMPLE",
        "owner_fb_id": "",
        "owner_telegram_token": "",
        "owner_telegram_chat_id": "",
        "dti_permit_url": "https://drive.google.com/EXAMPLE-DTI",
        "balsa_photos_url": "https://www.facebook.com/balsa-photos",
        "google_calendar_id": "",
        "google_calendar_api_key": "",
        "number_of_balsas": "1",
        "balsa_photos_json": "{\"balsa1\": \"https://facebook.com/balsa1-photos\", \"balsa2\": \"https://facebook.com/balsa2-photos\"}",
        "food_package": "Not available - bring your own food",
        "food_price": "",
        "buddle_price": "",
        "cancellation_policy": "No refund sa downpayment kung cancel 1 day before."
    },
    "ai_system_prompt": "Ikaw ay friendly parang tao assistant ni {name} sa {location}. Taglish, may po. Day Tour ONLY {price_day} 7am-4pm WALANG overnight. Capacity {capacity}, Inclusions {inclusions}, Maps {google_maps_link}, DTI {dti_permit_url}, Photos {balsa_photos_url}, Contact {contact}, GCash {gcash_number} ({gcash_name}) Down {downpayment}."
}

# === V5.1 CYBERSHIELD THEME - exact from screenshot ===
COLORS = {
    "bg": "#141a20",       # outer dark bg
    "card": "#1f252e",     # main panels (Installed Apps list)
    "card2": "#2a3441",    # button/card bg (Quick Actions)
    "border": "#2e3a47",   # subtle border
    "accent": "#3a5a7c",   # V5.1 blue (Quick Actions buttons)
    "accent2": "#4a6fa5",  # hover blue
    "green": "#5fb078",    # Safe (Clean) green
    "green2": "#3d7a4a",   # Lock USB Debugging green
    "orange": "#c9a86a",   # Low Risk yellowish (V5.1)
    "text": "#e6edf3",     # main text (light gray)
    "text2": "#8a95a8",    # secondary text
    "red": "#a33d3d",      # Auto Remove Virus red
    "yellow": "#c9a86a",
    "muted": "#5a6b7a",
    "console": "#1a2129",  # console log bg
}

class CCPTMessengerBot(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MQS ChatPilot v3.0 - Multi-Balsa")
        self.geometry("1280x800")
        self.configure(fg_color=COLORS["bg"])
        self.overrideredirect(True)
        self._offset_x = 0
        self._offset_y = 0

        # --- MULTI-CLIENT SYSTEM ---
        self.clients = self.load_clients()
        self.active_client_id = self.clients[0]["id"] if self.clients else "default"
        self.config_data = self.get_active_client()["config"]
        self.bookings = self.load_bookings()
        self.sessions = {}  
        self.flask_app = None
        self.flask_thread = None
        self.server_running = False
        self.message_count = 0
        self.auto_replies = 0

        self._build_titlebar()
        self._build_client_tabs()
        self._build_ui()
        self._init_flask()
        self.start_server()
        try:
            self.wm_attributes('-transparentcolor', 'black')
        except: pass
        self._start_reminder_loop()

    # ---------- CONFIG & BOOKINGS ----------
    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for k, v in DEFAULT_CONFIG.items():
                        if k not in data:
                            data[k] = v
                    # merge business_info too
                    for k, v in DEFAULT_CONFIG["business_info"].items():
                        if k not in data.get("business_info",{}):
                            data["business_info"][k] = v
                    return data
            except Exception as e:
                print(f"config load error {e}")
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=4, ensure_ascii=False)
            # also sync to active client
            try:
                ac = self.get_active_client()
                if ac is not None:
                    ac["config"] = json.loads(json.dumps(self.config_data))
                    ac["name"] = self.config_data.get("business_info",{}).get("name", ac["name"])
                    self.save_clients()
            except: pass
            self.refresh_client_tabs()
            self.log("✓ Config saved.")
        except Exception as e:
            self.log(f"✗ Save error: {e}")

    # ---------- MULTI-CLIENT MANAGER ----------
    def load_clients(self):
        # migrate from old config.json if clients.json not exists
        if os.path.exists(CLIENTS_PATH):
            try:
                with open(CLIENTS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data)>0:
                        return data
            except: pass
        # create first client from existing config or default
        base_cfg = None
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    base_cfg = json.load(f)
            except: base_cfg = None
        if not base_cfg:
            base_cfg = DEFAULT_CONFIG.copy()
            base_cfg["business_info"] = DEFAULT_CONFIG["business_info"].copy()
        clients = [{
            "id": "balsa_1",
            "name": base_cfg.get("business_info",{}).get("name","Balsa 1"),
            "page_id": "",
            "config": base_cfg
        }]
        try:
            with open(CLIENTS_PATH, 'w', encoding='utf-8') as f:
                json.dump(clients, f, indent=4, ensure_ascii=False)
        except: pass
        return clients

    def save_clients(self):
        try:
            with open(CLIENTS_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.clients, f, indent=4, ensure_ascii=False)
            # also keep config.json in sync for active
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.get_active_client()["config"], f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"✗ save clients error: {e}")

    def sync_to_cloud(self):
        try:
            import requests
            url = "https://mqs-chatpilot.onrender.com/admin/sync"
            headers = {"X-SYNC-TOKEN": "mqs_sync_2026", "Content-Type": "application/json"}
            # ensure latest clients saved
            self.save_clients()
            r = requests.post(url, json={"clients": self.clients}, headers=headers, timeout=12)
            if r.status_code == 200:
                # also sync blocked dates per balsa + vacation
                for c in self.clients:
                    try:
                        blocked = []
                        p = resource_path(f"blocked_{c['id']}.json")
                        if os.path.exists(p):
                            with open(p, 'r', encoding='utf-8') as f:
                                blocked = json.load(f)
                        vac = {"enabled": c["config"].get("vacation_enabled", False), "until": c["config"].get("vacation_until",""), "reason": c["config"].get("vacation_reason","Vacation")}
                        requests.post("https://mqs-chatpilot.onrender.com/admin/blocked", json={"balsa_id": c["id"], "blocked": blocked, "vacation": vac}, headers=headers, timeout=8)
                    except: pass
                messagebox.showinfo("Synced", f"Synced {len(self.clients)} balsas + blocked dates to cloud! Live na agad.")
                self.log(f"☁ Synced {len(self.clients)} clients + blocked to cloud ✓")
            else:
                messagebox.showwarning("Sync failed", f"{r.status_code}: {r.text[:200]}")
                self.log(f"✗ Sync failed {r.status_code}: {r.text[:120]}")
        except Exception as e:
            messagebox.showerror("Sync error", str(e))
            self.log(f"✗ Sync error: {e}")

    def get_active_client(self):
        for c in self.clients:
            if c["id"] == self.active_client_id:
                return c
        return self.clients[0] if self.clients else None

    def get_client_by_page_id(self, page_id):
        if not page_id:
            return None
        for c in self.clients:
            if c.get("page_id","") and c.get("page_id")==str(page_id):
                return c
            # also match by token? fallback: check config token contains page_id? not reliable
        return None

    def switch_client(self, client_id):
        # save current before switch
        self.save_clients()
        self.active_client_id = client_id
        self.config_data = self.get_active_client()["config"]
        self.bookings = self.load_bookings()
        self.sessions = {}
        self.refresh_client_tabs()
        self.reload_ui_from_config()
        self.refresh_bookings()
        try: self.refresh_dashboard()
        except: pass
        self.log(f"⇄ Switched to: {self.get_active_client()['name']} ({client_id})")

    def reload_ui_from_config(self):
        # update all entry fields from new config_data
        try:
            cfg = self.config_data
            self.token_entry.delete(0, "end")
            self.token_entry.insert(0, cfg.get("page_access_token",""))
            self.verify_entry.delete(0, "end")
            self.verify_entry.insert(0, cfg.get("verify_token","mqs_verify_2026"))
            self.port_entry.delete(0, "end")
            self.port_entry.insert(0, str(cfg.get("port",5000)))
            cur = cfg.get("ai_provider","gemini")
            self.ai_combo.set(cur if cur in ["gemini","openai"] else "local (no AI - template + booking logic)")
            self.ai_key_entry.delete(0, "end")
            self.ai_key_entry.insert(0, cfg.get("ai_api_key",""))
            for k, e in self.biz_entries.items():
                e.delete(0, "end")
                e.insert(0, str(cfg.get("business_info",{}).get(k,"")))
            self.webhook_label.configure(text=f"http://localhost:{cfg.get('port',5000)}/webhook")
            self._update_toggle_text()
            try:
                self.vac_var.set("on" if cfg.get("vacation_enabled") else "off")
                self.vac_switch.configure(text_color=COLORS["red"] if cfg.get("vacation_enabled") else COLORS["text2"])
                self.vac_label.configure(text=self._vac_text())
                self.refresh_blocked()
                self.refresh_dashboard()
            except: pass
        except Exception as e:
            self.log(f"reload ui error: {e}")

    def add_client(self):
        win = ctk.CTkToplevel(self)
        win.title("Add New Balsa Client")
        win.geometry("420x380")
        win.configure(fg_color=COLORS["card"])
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="➕  Add New Balsa Client", font=("Segoe UI", 14, "bold"), text_color=COLORS["accent"]).pack(pady=14)
        ctk.CTkLabel(win, text="Balsa Name (e.g., Balsa ni Pedro)", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=20)
        name_e = ctk.CTkEntry(win, width=380, height=38, font=("Segoe UI", 12))
        name_e.pack(padx=20, pady=6)
        name_e.insert(0, f"Balsa {len(self.clients)+1}")
        ctk.CTkLabel(win, text="GCash Number", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=20)
        gcash_e = ctk.CTkEntry(win, width=380, height=38, font=("Segoe UI", 12))
        gcash_e.pack(padx=20, pady=6)
        gcash_e.insert(0, "09123456789")
        ctk.CTkLabel(win, text="Price Day Tour (e.g., 3500)", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=20)
        price_e = ctk.CTkEntry(win, width=380, height=38, font=("Segoe UI", 12))
        price_e.pack(padx=20, pady=6)
        price_e.insert(0, "3500")
        def save():
            nm = name_e.get().strip() or f"Balsa {len(self.clients)+1}"
            new_id = f"balsa_{len(self.clients)+1}_{int(time.time())%1000}"
            new_cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
            new_cfg["business_info"]["name"] = nm
            new_cfg["business_info"]["gcash_number"] = gcash_e.get().strip()
            new_cfg["business_info"]["gcash_name"] = nm
            new_cfg["business_info"]["price_day"] = f"{price_e.get().strip()} (7am-4pm) - Day Tour ONLY"
            new_cfg["business_info"]["price_day_amount"] = price_e.get().strip()
            new_cfg["page_access_token"] = ""
            client = {"id": new_id, "name": nm, "page_id": "", "config": new_cfg}
            self.clients.append(client)
            self.save_clients()
            self.refresh_client_tabs()
            self.switch_client(new_id)
            win.destroy()
            self.log(f"➕ Added client: {nm} ({new_id})")
            messagebox.showinfo("Added", f"Added {nm}!\nFill-up Page Token at GCash sa left panel, then SAVE.")
        ctk.CTkButton(win, text="✅ Create Balsa Tab", fg_color=COLORS["green2"], hover_color=COLORS["green"], height=38, font=("Segoe UI", 12, "bold"), command=save).pack(pady=16, padx=20, fill="x")
        ctk.CTkButton(win, text="Cancel", fg_color=COLORS["card2"], height=32, command=win.destroy).pack(padx=20, fill="x")

    def rename_active_client(self):
        c = self.get_active_client()
        if not c: return
        win = ctk.CTkToplevel(self)
        win.title("Rename")
        win.geometry("360x180")
        win.configure(fg_color=COLORS["card"])
        win.transient(self); win.grab_set()
        ctk.CTkLabel(win, text="Rename Balsa", font=("Segoe UI", 12, "bold"), text_color=COLORS["text"]).pack(pady=10)
        e = ctk.CTkEntry(win, width=320, height=38)
        e.pack(padx=20, pady=6); e.insert(0, c["name"])
        def save():
            c["name"] = e.get().strip() or c["name"]
            c["config"]["business_info"]["name"] = c["name"]
            self.save_clients()
            self.refresh_client_tabs()
            win.destroy()
        ctk.CTkButton(win, text="Save", fg_color=COLORS["accent2"], command=save).pack(pady=10)

    def delete_active_client(self):
        if len(self.clients) <= 1:
            messagebox.showwarning("Error", "Need at least 1 balsa tab!")
            return
        c = self.get_active_client()
        if not messagebox.askyesno("Delete", f"Delete {c['name']}?\nMabubura din bookings nya!"):
            return
        self.clients = [x for x in self.clients if x["id"] != self.active_client_id]
        # delete bookings file
        try:
            os.remove(resource_path(f"bookings_{self.active_client_id}.json"))
        except: pass
        self.active_client_id = self.clients[0]["id"]
        self.config_data = self.get_active_client()["config"]
        self.bookings = self.load_bookings()
        self.save_clients()
        self.refresh_client_tabs()
        self.reload_ui_from_config()
        self.refresh_bookings()
        self.log(f"🗑 Deleted client {c['name']}")

    def _build_client_tabs(self):
        self.client_tabs_frame = ctk.CTkFrame(self, fg_color=COLORS["card2"], corner_radius=0, height=44, border_width=0)
        self.client_tabs_frame.pack(fill="x", padx=0, pady=0)
        self.client_tabs_scroll = ctk.CTkScrollableFrame(self.client_tabs_frame, fg_color="transparent", height=44, orientation="horizontal")
        self.client_tabs_scroll.pack(fill="both", expand=True, padx=6, pady=4)
        self.refresh_client_tabs()

    def refresh_client_tabs(self):
        try:
            for w in self.client_tabs_scroll.winfo_children():
                w.destroy()
            for c in self.clients:
                is_active = c["id"] == self.active_client_id
                btn = ctk.CTkButton(self.client_tabs_scroll, text=c["name"], width=140, height=32,
                    fg_color=COLORS["accent2"] if is_active else COLORS["card"],
                    hover_color=COLORS["accent"] if is_active else COLORS["border"],
                    border_width=1, border_color=COLORS["accent"] if is_active else COLORS["border"],
                    font=("Segoe UI", 11, "bold") if is_active else ("Segoe UI", 11),
                    text_color="white" if is_active else COLORS["text2"],
                    command=lambda cid=c["id"]: self.switch_client(cid))
                btn.pack(side="left", padx=4)
            # + tab
            ctk.CTkButton(self.client_tabs_scroll, text="＋  Add Balsa", width=110, height=32, fg_color=COLORS["green2"], hover_color=COLORS["green"], font=("Segoe UI", 11, "bold"), command=self.add_client).pack(side="left", padx=8)
            ctk.CTkButton(self.client_tabs_scroll, text="☁ Sync to Cloud", width=120, height=32, fg_color="#4a6fa5", hover_color="#3a5a7c", font=("Segoe UI", 11, "bold"), command=self.sync_to_cloud).pack(side="left", padx=8)
            # rename/delete for active
            ctk.CTkButton(self.client_tabs_scroll, text="✏ Rename", width=80, height=32, fg_color="transparent", border_width=1, border_color=COLORS["border"], text_color=COLORS["text2"], font=("Segoe UI", 10), command=self.rename_active_client).pack(side="left", padx=4)
            ctk.CTkButton(self.client_tabs_scroll, text="🗑", width=40, height=32, fg_color="transparent", border_width=1, border_color=COLORS["red"], text_color=COLORS["red"], font=("Segoe UI", 11), command=self.delete_active_client).pack(side="left", padx=2)
            # count
            ctk.CTkLabel(self.client_tabs_scroll, text=f"  {len(self.clients)} balsas", font=("Segoe UI", 10), text_color="gray").pack(side="left", padx=8)
        except Exception as e:
            print(f"tabs refresh error {e}")



    def load_bookings(self):
        # per-client bookings file
        active = getattr(self, 'active_client_id', 'default')
        per_path = resource_path(f"bookings_{active}.json")
        # migrate old bookings.json if exists and per-client not exists
        if not os.path.exists(per_path) and os.path.exists(BOOKINGS_PATH):
            try:
                import shutil; shutil.copy(BOOKINGS_PATH, per_path)
            except: pass
        path = per_path if os.path.exists(per_path) else BOOKINGS_PATH
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except: pass
        return []

    def save_bookings(self):
        try:
            active = getattr(self, 'active_client_id', 'default')
            per_path = resource_path(f"bookings_{active}.json")
            with open(per_path, 'w', encoding='utf-8') as f:
                json.dump(self.bookings, f, indent=4, ensure_ascii=False)
            # also keep old file in sync for fallback
            with open(BOOKINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.bookings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"✗ bookings save error: {e}")

    # ---------- BLOCKED DATES & VACATION ----------
    def _blocked_path(self):
        return resource_path(f"blocked_{self.active_client_id}.json")

    def load_blocked_dates(self):
        p = self._blocked_path()
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list): return data
            except: pass
        return []

    def save_blocked_dates(self, data):
        try:
            with open(self._blocked_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"✗ blocked save error: {e}")

    def is_vacation_active(self):
        if not self.config_data.get("vacation_enabled"): return False, None
        until = self.config_data.get("vacation_until","").strip()
        if not until: return True, self.config_data.get("vacation_reason","Vacation")
        try:
            import datetime as _dt
            # parse until date
            for fmt in ("%Y-%m-%d","%m/%d/%Y","%d/%m/%Y"):
                try:
                    d = _dt.datetime.strptime(until, fmt).date()
                    if _dt.date.today() <= d:
                        return True, self.config_data.get("vacation_reason","Vacation")
                    else:
                        return False, None
                except: continue
            # fallback: if can't parse, treat as active
            return True, self.config_data.get("vacation_reason","Vacation")
        except: return True, self.config_data.get("vacation_reason","Vacation")

    def is_date_blocked(self, date_str):
        """Check vacation + blocked ranges. Returns (blocked_bool, reason, block_obj)."""
        # vacation first
        is_vac, reason = self.is_vacation_active()
        if is_vac:
            until = self.config_data.get("vacation_until","")
            return True, f"Vacation ({reason}) until {until}" if until else f"Vacation ({reason})", {"id":"VACATION","reason":reason}
        # check blocked ranges
        try:
            import datetime as _dt
            qdate = self.parse_booking_date_local(date_str)
            if not qdate: return False, None, None
            for blk in self.load_blocked_dates():
                try:
                    s = _dt.datetime.strptime(blk.get("start",""), "%Y-%m-%d").date()
                    e = _dt.datetime.strptime(blk.get("end",""), "%Y-%m-%d").date()
                    if s <= qdate <= e:
                        return True, blk.get("reason","Blocked"), blk
                except: continue
        except: pass
        return False, None, None

    def check_availability(self, date_str):
        """Check if date is already booked OR blocked/vacation. Returns (available, info)."""
        # first check vacation/blocked
        blocked, reason, blk = self.is_date_blocked(date_str)
        if blocked:
            return False, {"customer_name": reason, "id": blk.get("id","BLOCKED"), "reason": reason, "blocked": True}
        date_str_l = date_str.strip().lower()
        for b in self.bookings:
            if b.get("status") in ["cancelled"]:
                continue
            bdate = b.get("date","").strip().lower()
            if not bdate:
                continue
            if bdate == date_str_l or bdate in date_str_l or date_str_l in bdate:
                return False, b
        return True, None

    def create_inquiry(self, sender_id, date, pax, name, contact, tour_type="Day Tour"):
        biz = self.config_data["business_info"]
        price = biz.get("price_day_amount", "3500")
        inquiry = {
            "id": f"INQ{int(time.time())%100000:05d}",
            "customer_fb_id": sender_id,
            "customer_name": name or "Unknown",
            "contact": contact,
            "date": date,
            "tour_type": tour_type,
            "pax": pax,
            "price": price,
            "downpayment": biz.get("downpayment","1000"),
            "gcash_number": biz.get("gcash_number",""),
            "gcash_name": biz.get("gcash_name",""),
            "status": "INQUIRY",
            "gcash_ref": "",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.bookings.append(inquiry)
        self.save_bookings()
        try: self.after(0, self.refresh_bookings)
        except: pass
        self.log(f"📩 NEW INQUIRY (not confirmed): {inquiry['id']} | {name} | {date} | {pax} pax")
        try: self._booking_notif(inquiry)
        except: pass
        try: self.send_owner_notif(inquiry, "INQUIRY")
        except: pass
        return inquiry

    def create_pending_booking(self, sender_id, date, pax, name, contact, tour_type="Day Tour"): 
        biz = self.config_data["business_info"]
        # determine price
        if "night" in tour_type.lower():
            price = biz.get("price_night_amount", "4500")
        elif "22" in tour_type:
            price = biz.get("price_22hrs", "7000")
        else:
            price = biz.get("price_day_amount", "3500")
        booking = {
            "id": f"BK{int(time.time())%100000:05d}",
            "customer_fb_id": sender_id,
            "customer_name": name,
            "contact": contact,
            "date": date,
            "tour_type": tour_type,
            "pax": pax,
            "price": price,
            "downpayment": biz.get("downpayment","1000"),
            "gcash_number": biz.get("gcash_number",""),
            "gcash_name": biz.get("gcash_name",""),
            "status": "PENDING_PAYMENT",
            "gcash_ref": "",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.bookings.append(booking)
        self.save_bookings()
        try: self.after(0, self.refresh_bookings)
        except: pass
        self.log(f"📝 NEW PENDING BOOKING: {booking['id']} | {name} | {date} | {pax} pax | {tour_type} | P{price} | Down P{booking['downpayment']}")
        try: self.send_owner_notif(booking, "BOOKING")
        except: pass
        # popup notif
        try: self.after(0, lambda: self._booking_notif(booking))
        except: self._booking_notif(booking)
        return booking

    def _booking_notif(self, booking):
        try:
            self.bell()
        except: pass
        self.log(f"🔔 OWNER NOTIF: May bagong inquiry/booking! {booking['customer_name']} - {booking['date']} - {booking['tour_type']} - Status: {booking['status']}")
        # update bookings tab badge
        try:
            self.bookings_count_label.configure(text=f"{len([b for b in self.bookings if b['status']!='cancelled'])} bookings")
        except: pass

    def send_owner_notif(self, booking, kind="BOOKING"):
        biz = self.config_data.get("business_info",{})
        owner_id = biz.get("owner_fb_id","").strip()
        # Build message
        if kind == "INQUIRY":
            msg = f"🔔 NEW INQUIRY (hindi pa nag-confirm) - {biz.get('name','')}\n👤 {booking.get('customer_name','')} - {booking.get('contact','')} (FB:{booking.get('customer_fb_id','')})\n📅 {booking.get('date','')} | 👥 {booking.get('pax','')} pax | 🏖 {booking.get('tour_type','')}\n💵 P{booking.get('price','')} Down P{booking.get('downpayment','')}\n⚠️ Hindi pa nag-confirm si client, tawagan nyo na po! {booking.get('contact','')}"
        elif kind == "PAID":
            msg = f"💰 PAID! - {biz.get('name','')}\n👤 {booking.get('customer_name','')} - {booking.get('contact','')} \n📅 {booking.get('date','')} | {booking.get('pax','')} pax\nRef: {booking.get('gcash_ref','')}\n→ I-confirm nyo sa app!"
        else:
            msg = f"📝 NEW HOLD BOOKING - {biz.get('name','')}\n👤 {booking.get('customer_name','')} - {booking.get('contact','')} (FB:{booking.get('customer_fb_id','')})\n📅 {booking.get('date','')} | 👥 {booking.get('pax','')} pax | 🏖 {booking.get('tour_type','')}\n💵 P{booking.get('price','')} Down P{booking.get('downpayment','')} → GCash {biz.get('gcash_number','')}\nStatus: {booking.get('status','')} - tawagan nyo: {booking.get('contact','')}"
        self.log(f"→ Owner notif [{kind}]: {msg[:120]}...")
        # Send to Owner FB if set
        if owner_id and owner_id.isdigit():
            token = self.config_data.get("page_access_token","")
            if token:
                try:
                    import requests
                    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
                    payload = {"recipient":{"id": owner_id}, "message":{"text": msg}}
                    r = requests.post(url, json=payload, timeout=10)
                    if r.status_code==200:
                        self.log(f"✓ Owner FB notified ({owner_id})")
                    else:
                        self.log(f"✗ Owner FB fail {r.status_code}: {r.text[:120]}")
                except Exception as e:
                    self.log(f"✗ Owner FB error: {e}")
        # Telegram optional
        tg_token = biz.get("owner_telegram_token","").strip()
        tg_chat = biz.get("owner_telegram_chat_id","").strip()
        if tg_token and tg_chat:
            try:
                import requests
                url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                r = requests.post(url, json={"chat_id": tg_chat, "text": msg}, timeout=10)
                if r.status_code==200:
                    self.log(f"✓ Owner Telegram notified")
                else:
                    self.log(f"✗ Telegram fail: {r.text[:100]}")
            except Exception as e:
                self.log(f"✗ Telegram error: {e}")


    def mark_paid(self, sender_id, ref):
        # find latest pending for this sender
        for b in reversed(self.bookings):
            if b.get("customer_fb_id")==sender_id and b.get("status")=="PENDING_PAYMENT":
                b["status"] = "PAID_AWAITING_CONFIRM"
                b["gcash_ref"] = ref
                b["paid_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_bookings()
                try: self.refresh_bookings()
                except: pass
                self.log(f"💰 PAYMENT RECEIVED: {b['id']} Ref:{ref} -> PAID_AWAITING_CONFIRM (owner need to CONFIRM in Bookings tab)")
                return b
        return None

    # ---------- TITLEBAR ----------
    def _build_titlebar(self):
        self.titlebar = ctk.CTkFrame(self, fg_color=COLORS["card"], height=42, corner_radius=0)
        self.titlebar.pack(fill="x", side="top")
        self.titlebar.bind("<Button-1>", self._start_move)
        self.titlebar.bind("<B1-Motion>", self._do_move)
        left = ctk.CTkFrame(self.titlebar, fg_color="transparent")
        left.pack(side="left", padx=12, pady=6)
        left.bind("<Button-1>", self._start_move)
        left.bind("<B1-Motion>", self._do_move)
        ctk.CTkLabel(left, text="●", text_color=COLORS["accent"], font=("Arial", 20)).pack(side="left", padx=(0,6))
        title = ctk.CTkLabel(left, text="MQS ChatPilot", font=("Segoe UI", 13, "bold"), text_color=COLORS["text"])
        title.pack(side="left")
        title.bind("<Button-1>", self._start_move)
        title.bind("<B1-Motion>", self._do_move)
        ctk.CTkLabel(left, text="  v2.0 BOOKING SYSTEM  •  by MQS TECH • ChatPilot AI", font=("Segoe UI", 12), text_color=COLORS["text2"]).pack(side="left", padx=8)
        right = ctk.CTkFrame(self.titlebar, fg_color="transparent")
        right.pack(side="right", padx=6)
        min_btn = ctk.CTkButton(right, text="—", width=36, height=34, fg_color="#2d3748", hover_color="#3a4556", command=self._minimize, font=("Arial", 12))
        min_btn.pack(side="left", padx=2)
        close_btn = ctk.CTkButton(right, text="✕", width=36, height=34, fg_color=COLORS["red"], hover_color="#cc0033", command=self.destroy, font=("Arial", 12, "bold"))
        close_btn.pack(side="left", padx=2)

    def _start_move(self, e):
        self._offset_x = e.x
        self._offset_y = e.y
    def _do_move(self, e):
        x = self.winfo_pointerx() - self._offset_x
        y = self.winfo_pointery() - self._offset_y
        self.geometry(f"+{x}+{y}")
    def _minimize(self):
        self.overrideredirect(False)
        self.iconify()
        self.after(100, self._poll_minimize)
    def _poll_minimize(self):
        if self.state() == 'normal':
            self.overrideredirect(True)
            try: self.wm_attributes('-transparentcolor', 'black')
            except: pass
        else:
            self.after(100, self._poll_minimize)

    # ---------- UI ----------
    def _build_ui(self):
        status_frame = ctk.CTkFrame(self, fg_color=COLORS["card2"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        status_frame.pack(fill="x", padx=12, pady=(10,6))
        self.status_dot = ctk.CTkLabel(status_frame, text="●", font=("Arial", 22), text_color="gray")
        self.status_dot.pack(side="left", padx=(14,4), pady=8)
        self.status_label = ctk.CTkLabel(status_frame, text="Server: Starting...", font=("Segoe UI", 10, "bold"), text_color=COLORS["text"])
        self.status_label.pack(side="left", pady=8)
        self.stats_label = ctk.CTkLabel(status_frame, text="Messages: 0 | Auto-replies: 0 | Bookings: 0", font=("Segoe UI", 12), text_color=COLORS["text2"])
        self.stats_label.pack(side="left", padx=20)
        self.toggle_var = ctk.StringVar(value="on" if self.config_data.get("auto_reply_enabled") else "off")
        self.toggle = ctk.CTkSwitch(status_frame, text="AUTO-REPLY ON", command=self.toggle_auto_reply,
                                    variable=self.toggle_var, onvalue="on", offvalue="off",
                                    progress_color=COLORS["green"], font=("Segoe UI", 10, "bold"), text_color=COLORS["green"])
        self.toggle.pack(side="right", padx=12, pady=8)
        self._update_toggle_text()

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=12, pady=6)

        # left - config (scrollable)
        left = ctk.CTkFrame(main, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"], width=400)
        left.pack(side="left", fill="y", padx=(0,6))
        left.pack_propagate(False)
        ctk.CTkLabel(left, text="⚙  CONFIGURATION", font=("Segoe UI", 14, "bold"), text_color=COLORS["accent"]).pack(pady=(12,6), padx=12, anchor="w")
        scroll = ctk.CTkScrollableFrame(left, fg_color="transparent", width=380, height=640)
        scroll.pack(fill="both", expand=True, padx=6, pady=6)

        ctk.CTkLabel(scroll, text="Facebook Page Access Token *", font=("Segoe UI", 9, "bold"), text_color=COLORS["text2"]).pack(anchor="w", padx=4, pady=(4,2))
        self.token_entry = ctk.CTkEntry(scroll, placeholder_text="EAAx... (from Meta Developer)", show="•", height=38, font=("Segoe UI", 12))
        self.token_entry.pack(fill="x", padx=4, pady=2)
        self.token_entry.insert(0, self.config_data.get("page_access_token",""))
        ctk.CTkButton(scroll, text="👁 Show/Hide", height=32, width=80, font=("Segoe UI", 11), fg_color=COLORS["card2"], command=self._toggle_token).pack(anchor="w", padx=4, pady=2)

        ctk.CTkLabel(scroll, text="Verify Token", font=("Segoe UI", 9, "bold"), text_color=COLORS["text2"]).pack(anchor="w", padx=4, pady=(8,2))
        self.verify_entry = ctk.CTkEntry(scroll, height=34, font=("Segoe UI", 12))
        self.verify_entry.pack(fill="x", padx=4, pady=2)
        self.verify_entry.insert(0, self.config_data.get("verify_token","mqs_verify_2026"))

        ctk.CTkLabel(scroll, text="Port", font=("Segoe UI", 9, "bold"), text_color=COLORS["text2"]).pack(anchor="w", padx=4, pady=(8,2))
        self.port_entry = ctk.CTkEntry(scroll, height=34, font=("Segoe UI", 12), width=100)
        self.port_entry.pack(anchor="w", padx=4, pady=2)
        self.port_entry.insert(0, str(self.config_data.get("port",5000)))

        ctk.CTkLabel(scroll, text="AI Provider", font=("Segoe UI", 9, "bold"), text_color=COLORS["text2"]).pack(anchor="w", padx=4, pady=(10,2))
        self.ai_combo = ctk.CTkOptionMenu(scroll, values=["gemini", "openai", "local (no AI - template + booking logic)"], command=self._on_ai_change, width=260, fg_color=COLORS["card2"], button_color=COLORS["accent2"])
        self.ai_combo.pack(anchor="w", padx=4, pady=2)
        cur = self.config_data.get("ai_provider","gemini")
        self.ai_combo.set(cur if cur in ["gemini","openai"] else "local (no AI - template + booking logic)")

        ctk.CTkLabel(scroll, text="AI API Key", font=("Segoe UI", 9, "bold"), text_color=COLORS["text2"]).pack(anchor="w", padx=4, pady=(6,2))
        self.ai_key_entry = ctk.CTkEntry(scroll, placeholder_text="AIza... (Gemini) or sk-... (OpenAI)", show="•", height=34, font=("Segoe UI", 12))
        self.ai_key_entry.pack(fill="x", padx=4, pady=2)
        self.ai_key_entry.insert(0, self.config_data.get("ai_api_key",""))

        ctk.CTkLabel(scroll, text="— BUSINESS INFO (ituturo kay AI) —", font=("Segoe UI", 9, "bold"), text_color=COLORS["accent"]).pack(anchor="w", padx=4, pady=(12,4))
        self.biz_entries = {}
        biz = self.config_data.get("business_info",{})
        fields = [
            ("name", "Balsa / Business Name"),
            ("location", "Location"),
            ("google_maps_link", "Google Maps Link (pin)"),
            ("price_day", "Price Day Tour (display)"),
            ("price_day_amount", "Day Amount (e.g., 3500)"),
            ("capacity", "Capacity (e.g., 15-20 pax)"),
            ("inclusions", "Inclusions (e.g., cottage, videoke...)"),
            ("contact", "Contact Number (fallback if AI can't answer)"),
            ("gcash_number", "GCash Number"),
            ("gcash_name", "GCash Name"),
            ("downpayment", "Downpayment (e.g., 1000)"),
            ("dti_permit_url", "DTI / Permit Image Link (Google Drive)"),
            ("balsa_photos_url", "Balsa Photos Link (FB Album / Drive)"),
            ("owner_fb_id", "Owner FB ID (for notifications) - find at findmyfbid.com"),
            ("owner_telegram_token", "Telegram Bot Token (optional)"),
            ("owner_telegram_chat_id", "Telegram Chat ID (optional)"),
            ("google_calendar_id", "Google Calendar ID (e.g., abc@group.calendar.google.com)"),
            ("google_calendar_api_key", "Google Calendar API Key (from Google Cloud)"),
            ("number_of_balsas", "Number of Balsas (1-5)"),
            ("balsa_photos_json", "Balsa Photos JSON (per balsa links)"),
            ("food_package", "Food Package Details (e.g., bring own / buddle)"),
            ("food_price", "Food Price (e.g., 500)"),
            ("buddle_price", "Buddle Price (e.g., 1500)"),
            ("extra_info", "Extra Info"),
            ("cancellation_policy", "Cancellation Policy"),
        ]
        for key, label in fields:
            ctk.CTkLabel(scroll, text=label, font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=4, pady=(6,0))
            e = ctk.CTkEntry(scroll, height=34, font=("Segoe UI", 12))
            e.pack(fill="x", padx=4, pady=1)
            e.insert(0, str(biz.get(key,"")))
            self.biz_entries[key] = e

        ctk.CTkButton(scroll, text="💾  SAVE CONFIG", fg_color=COLORS["accent2"], hover_color=COLORS["accent"], font=("Segoe UI", 10, "bold"), height=34, command=self.save_ui_config).pack(fill="x", padx=4, pady=10)
        ctk.CTkButton(scroll, text="🔗  How to get Page Token? (Guide)", fg_color="transparent", border_width=1, border_color=COLORS["border"], text_color=COLORS["text2"], font=("Segoe UI", 11), height=34, command=self.open_guide).pack(fill="x", padx=4, pady=2)
        ctk.CTkButton(scroll, text="▶  Restart Server", fg_color=COLORS["green2"], hover_color=COLORS["green"], height=34, font=("Segoe UI", 9, "bold"), command=self.restart_server).pack(fill="x", padx=4, pady=4)

        info = ctk.CTkFrame(scroll, fg_color=COLORS["card2"], corner_radius=8)
        info.pack(fill="x", padx=4, pady=8)
        ctk.CTkLabel(info, text="Webhook URL (ilagay sa Meta Developer):", font=("Segoe UI", 8, "bold"), text_color=COLORS["text2"]).pack(anchor="w", padx=8, pady=(8,2))
        self.webhook_label = ctk.CTkLabel(info, text="http://localhost:5000/webhook", font=("Consolas", 11), text_color=COLORS["accent"])
        self.webhook_label.pack(anchor="w", padx=8, pady=2)
        ctk.CTkLabel(info, text="Verify Token: mqs_verify_2026", font=("Segoe UI", 10), text_color=COLORS["text2"]).pack(anchor="w", padx=8, pady=(2,4))
        ctk.CTkLabel(info, text="Tip: ngrok http 5000 para public", font=("Consolas", 10), text_color="gray").pack(anchor="w", padx=8, pady=(2,8))

        # right - TABVIEW: Logs + Bookings
        right = ctk.CTkFrame(main, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        right.pack(side="right", fill="both", expand=True)

        # CTkTabview case varies by version
        TabView = getattr(ctk, "CTkTabView", getattr(ctk, "CTkTabview", None))
        self.tabview = TabView(right, fg_color=COLORS["card"], segmented_button_fg_color=COLORS["card2"], segmented_button_selected_color=COLORS["accent2"], segmented_button_selected_hover_color=COLORS["accent"], text_color=COLORS["text"])
        self.tabview.pack(fill="both", expand=True, padx=8, pady=8)
        self.tabview.add("💬  LIVE CHAT & LOGS")
        self.tabview.add("📅  BOOKINGS CALENDAR")

        # --- TAB 1: LOGS ---
        tab1 = self.tabview.tab("💬  LIVE CHAT & LOGS")
        top_btns = ctk.CTkFrame(tab1, fg_color="transparent")
        top_btns.pack(fill="x", padx=6, pady=8)
        ctk.CTkLabel(top_btns, text="💬  LIVE MESSAGES", font=("Segoe UI", 10, "bold"), text_color=COLORS["accent"]).pack(side="left")
        ctk.CTkButton(top_btns, text="Clear", width=60, height=34, fg_color=COLORS["card2"], font=("Segoe UI", 11), command=self.clear_logs).pack(side="right", padx=4)
        ctk.CTkButton(top_btns, text="Test Booking Flow", width=130, height=34, fg_color=COLORS["orange"], hover_color="#e65100", font=("Segoe UI", 8, "bold"), command=self.test_ai).pack(side="right", padx=4)

        test_frame = ctk.CTkFrame(tab1, fg_color=COLORS["card2"], corner_radius=8)
        test_frame.pack(fill="x", padx=6, pady=(0,6))
        ctk.CTkLabel(test_frame, text="Simulate Customer (test booking flow without FB):", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=8, pady=(6,2))
        row = ctk.CTkFrame(test_frame, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(2,4))
        self.test_entry = ctk.CTkEntry(row, placeholder_text="Hal: Magkano po? Gusto ko magbook sa Aug 30, 15 pax, Day tour", font=("Segoe UI", 12), height=38)
        self.test_entry.pack(side="left", fill="x", expand=True, padx=(0,6))
        self.test_entry.bind("<Return>", lambda e: self.test_ai())
        ctk.CTkButton(row, text="Send →", width=70, height=38, fg_color=COLORS["accent2"], command=self.test_ai).pack(side="right")
        # quick quick replies
        quick = ctk.CTkFrame(test_frame, fg_color="transparent")
        quick.pack(fill="x", padx=8, pady=(0,8))
        for txt in ["Magkano balsa?", "Available Aug 30?", "15 pax kami", "Juan 09123456789", "GCash Ref 123456"]:
            ctk.CTkButton(quick, text=txt, height=20, font=("Segoe UI", 10), fg_color=COLORS["card"], border_width=1, border_color=COLORS["border"], command=lambda t=txt: self._quick_test(t)).pack(side="left", padx=2)

        self.log_box = ctk.CTkTextbox(tab1, font=("Consolas", 12), fg_color=COLORS["console"], text_color="#c0c8d0", border_width=1, border_color=COLORS["border"], corner_radius=8)
        self.log_box.pack(fill="both", expand=True, padx=6, pady=(0,6))
        self.sim_sender = "TEST_USER_001"
        ctk.CTkLabel(tab1, text="Simulated FB ID: TEST_USER_001 (to track booking session)", font=("Segoe UI", 10), text_color="gray").pack(pady=2)

        self.tabview.add("📊  DASHBOARD")
        # --- TAB 2: BOOKINGS ---
        tab2 = self.tabview.tab("📅  BOOKINGS CALENDAR")
        top2 = ctk.CTkFrame(tab2, fg_color="transparent")
        top2.pack(fill="x", padx=6, pady=8)
        ctk.CTkLabel(top2, text="📅  BOOKINGS", font=("Segoe UI", 14, "bold"), text_color=COLORS["accent"]).pack(side="left")
        self.bookings_count_label = ctk.CTkLabel(top2, text=f"{len(self.bookings)} bookings", font=("Segoe UI", 12), text_color=COLORS["text2"])
        self.bookings_count_label.pack(side="left", padx=8)
        ctk.CTkButton(top2, text="🔄 Refresh", width=70, height=34, fg_color=COLORS["card2"], command=self.refresh_bookings).pack(side="right", padx=2)
        ctk.CTkButton(top2, text="➕ Manual Add", width=90, height=34, fg_color=COLORS["green2"], hover_color=COLORS["green"], font=("Segoe UI", 8, "bold"), command=self.manual_add_booking).pack(side="right", padx=2)

        # stats cards
        stats_frame = ctk.CTkFrame(tab2, fg_color=COLORS["card2"], corner_radius=8)
        stats_frame.pack(fill="x", padx=6, pady=6)
        self.stat_pending = ctk.CTkLabel(stats_frame, text="⏳ Pending: 0", font=("Segoe UI", 9, "bold"), text_color=COLORS["yellow"])
        self.stat_pending.pack(side="left", padx=10, pady=6)
        self.stat_paid = ctk.CTkLabel(stats_frame, text="💰 Paid: 0", font=("Segoe UI", 9, "bold"), text_color=COLORS["orange"])
        self.stat_paid.pack(side="left", padx=10)
        self.stat_confirmed = ctk.CTkLabel(stats_frame, text="✅ Confirmed: 0", font=("Segoe UI", 9, "bold"), text_color=COLORS["green"])
        self.stat_confirmed.pack(side="left", padx=10)

        # vacation mode toggle + blocked summary
        vac_frame = ctk.CTkFrame(tab2, fg_color=COLORS["card2"], corner_radius=8, border_width=1, border_color=COLORS["border"])
        vac_frame.pack(fill="x", padx=6, pady=6)
        self.vac_var = ctk.StringVar(value="on" if self.config_data.get("vacation_enabled") else "off")
        self.vac_switch = ctk.CTkSwitch(vac_frame, text="🏖 Vacation Mode", command=self.toggle_vacation, variable=self.vac_var, onvalue="on", offvalue="off", progress_color=COLORS["red"], font=("Segoe UI", 9, "bold"), text_color=COLORS["red"] if self.config_data.get("vacation_enabled") else COLORS["text2"])
        self.vac_switch.pack(side="left", padx=10, pady=8)
        self.vac_label = ctk.CTkLabel(vac_frame, text=self._vac_text(), font=("Segoe UI", 9), text_color=COLORS["text2"])
        self.vac_label.pack(side="left", padx=6)
        ctk.CTkButton(vac_frame, text="⚙ Set Vacation", width=100, height=28, fg_color=COLORS["card"], border_width=1, border_color=COLORS["border"], command=self.set_vacation).pack(side="right", padx=6)
        ctk.CTkButton(vac_frame, text="🚫 Block Dates", width=110, height=28, fg_color=COLORS["red"], hover_color="#cc0033", command=self.block_dates_popup).pack(side="right", padx=6)

        # blocked dates list (calendar view)
        self.blocked_frame = ctk.CTkScrollableFrame(tab2, fg_color=COLORS["console"], corner_radius=8, height=70, border_width=1, border_color=COLORS["border"])
        self.blocked_frame.pack(fill="x", padx=6, pady=6)
        self.blocked_label = ctk.CTkLabel(self.blocked_frame, text="🚫 Blocked Dates: none", font=("Consolas", 10), text_color=COLORS["yellow"])
        self.blocked_label.pack(anchor="w", padx=6, pady=4)

        # availability checker
        avail_frame = ctk.CTkFrame(tab2, fg_color=COLORS["card2"], corner_radius=8)
        avail_frame.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(avail_frame, text="Check Availability:", font=("Segoe UI", 8, "bold"), text_color=COLORS["text2"]).pack(side="left", padx=8)
        self.avail_entry = ctk.CTkEntry(avail_frame, placeholder_text="e.g., 2026-08-30 or Aug 30", width=160, height=34, font=("Segoe UI", 12))
        self.avail_entry.pack(side="left", padx=4)
        ctk.CTkButton(avail_frame, text="Check", width=60, height=34, fg_color=COLORS["accent2"], command=self.check_avail_ui).pack(side="left", padx=4)
        self.avail_result = ctk.CTkLabel(avail_frame, text="", font=("Segoe UI", 9, "bold"), text_color=COLORS["text"])
        self.avail_result.pack(side="left", padx=8)

        self.bookings_scroll = ctk.CTkScrollableFrame(tab2, fg_color="transparent", height=320)
        self.bookings_scroll.pack(fill="both", expand=True, padx=6, pady=6)

        # --- TAB 3: DASHBOARD ---
        tab3 = self.tabview.tab("📊  DASHBOARD")
        dash_top = ctk.CTkFrame(tab3, fg_color="transparent")
        dash_top.pack(fill="x", padx=6, pady=8)
        ctk.CTkLabel(dash_top, text="📊  ANALYTICS DASHBOARD", font=("Segoe UI", 13, "bold"), text_color=COLORS["accent"]).pack(side="left")
        self.dash_balsa_label = ctk.CTkLabel(dash_top, text=f"— {self.get_active_client()['name']}", font=("Segoe UI", 10), text_color=COLORS["text2"])
        self.dash_balsa_label.pack(side="left", padx=8)
        ctk.CTkButton(dash_top, text="🔄 Refresh", width=80, height=30, fg_color=COLORS["card2"], command=self.refresh_dashboard).pack(side="right", padx=2)

        self.dash_cards_frame = ctk.CTkFrame(tab3, fg_color="transparent")
        self.dash_cards_frame.pack(fill="x", padx=6, pady=6)
        # cards will be created in refresh_dashboard
        self.dash_cards = {}
        # stats grid
        self.dash_stats_frame = ctk.CTkFrame(tab3, fg_color=COLORS["card2"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        self.dash_stats_frame.pack(fill="x", padx=6, pady=6)
        self.dash_revenue_label = ctk.CTkLabel(self.dash_stats_frame, text="💰 Revenue: --", font=("Segoe UI", 11, "bold"), text_color=COLORS["green"])
        self.dash_revenue_label.pack(anchor="w", padx=12, pady=(8,2))
        self.dash_peak_label = ctk.CTkLabel(self.dash_stats_frame, text="🔥 Peak: --", font=("Segoe UI", 11), text_color=COLORS["text"])
        self.dash_peak_label.pack(anchor="w", padx=12, pady=2)
        self.dash_pax_label = ctk.CTkLabel(self.dash_stats_frame, text="👥 Total Pax: --", font=("Segoe UI", 11), text_color=COLORS["text"])
        self.dash_pax_label.pack(anchor="w", padx=12, pady=2)
        self.dash_monthly_label = ctk.CTkLabel(self.dash_stats_frame, text="📅 Monthly: --", font=("Consolas", 10), text_color=COLORS["text2"])
        self.dash_monthly_label.pack(anchor="w", padx=12, pady=(2,8))
        # export
        ctk.CTkButton(tab3, text="📤 Export CSV", width=120, height=30, fg_color=COLORS["accent2"], command=self.export_dashboard_csv).pack(side="left", pady=6, padx=6)
        ctk.CTkButton(tab3, text="🖼 Verify GCash Screenshot", width=180, height=30, fg_color=COLORS["green2"], hover_color=COLORS["green"], command=self.upload_gcash_screenshot).pack(side="left", padx=6)
        ctk.CTkButton(tab3, text="⏰ Run Reminders Now", width=150, height=30, fg_color=COLORS["orange"], hover_color="#e65100", command=self.manual_trigger_reminders).pack(side="left", padx=6)
        # live cloud stats
        self.dash_cloud_label = ctk.CTkLabel(tab3, text="☁ Cloud stats: click Refresh", font=("Segoe UI", 10), text_color="gray")
        self.dash_cloud_label.pack(anchor="w", padx=6, pady=4)

        # footer
        footer = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=0, height=32)
        footer.pack(fill="x", side="bottom")
        ctk.CTkLabel(footer, text="© MQS TECH  •  Messenger AutoReply AI v2.0 Booking System  •  support@mqs.local", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(pady=4)

        self.after(500, lambda: self.log("=== MQS AutoReply v2.0 Booking System Started ==="))
        self.after(600, lambda: self.log("V2 Features: Auto-booking, GCash, Availability check, Standalone flow"))
        self.after(700, self.refresh_bookings)
        self.after(720, self.refresh_blocked)
        self.after(750, self.refresh_dashboard)
        self.after(800, lambda: self.log(f"Webhook: http://localhost:{self.config_data.get('port',5000)}/webhook"))

    def _quick_test(self, txt):
        self.test_entry.delete(0,"end")
        self.test_entry.insert(0, txt)
        self.test_ai()

    def _toggle_token(self):
        cur = self.token_entry.cget("show")
        self.token_entry.configure(show="" if cur=="•" else "•")

    def _on_ai_change(self, val):
        if "local" in val:
            self.config_data["ai_provider"] = "local"
        else:
            self.config_data["ai_provider"] = val

    def _update_toggle_text(self):
        enabled = self.toggle_var.get() == "on"
        self.toggle.configure(text="AUTO-REPLY ON" if enabled else "AUTO-REPLY OFF", text_color=COLORS["green"] if enabled else COLORS["red"], progress_color=COLORS["green"] if enabled else "gray")

    def toggle_auto_reply(self):
        enabled = self.toggle_var.get() == "on"
        self.config_data["auto_reply_enabled"] = enabled
        self._update_toggle_text()
        self.save_config()
        self.log(f"{'🟢 Auto-reply ENABLED' if enabled else '🔴 Auto-reply DISABLED'}")

    def save_ui_config(self):
        self.config_data["page_access_token"] = self.token_entry.get().strip()
        self.config_data["verify_token"] = self.verify_entry.get().strip() or "mqs_verify_2026"
        try:
            self.config_data["port"] = int(self.port_entry.get().strip())
        except: self.config_data["port"] = 5000
        prov = self.ai_combo.get()
        if "local" in prov: self.config_data["ai_provider"] = "local"
        elif "openai" in prov: self.config_data["ai_provider"] = "openai"
        else: self.config_data["ai_provider"] = "gemini"
        self.config_data["ai_api_key"] = self.ai_key_entry.get().strip()
        for k, e in self.biz_entries.items():
            self.config_data["business_info"][k] = e.get().strip()
        self.save_config()
        self.webhook_label.configure(text=f"http://localhost:{self.config_data['port']}/webhook")
        messagebox.showinfo("Saved", "Config saved! Bookings GCash/Capacity updated. AI will use new info.")
        self.log("✓ Business info updated - AI will use new GCash/Price/Capacity.")

    def open_guide(self):
        guide = "PAANO KUMUHA NG PAGE TOKEN:\n1. developers.facebook.com > My Apps > Create App (Business)\n2. Add Messenger Product\n3. Access Tokens > Generate\n4. Webhooks Callback: https://YOUR_NGROK/webhook Verify: mqs_verify_2026\n5. Subscribe messages"
        messagebox.showinfo("Guide", guide)

    def clear_logs(self):
        self.log_box.delete("1.0", "end")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        try:
            self.log_box.insert("end", line)
            self.log_box.see("end")
        except: pass
        print(line, end="")

    # ---------- BOOKINGS UI ----------
    def refresh_bookings(self):
        # clear
        for w in self.bookings_scroll.winfo_children():
            w.destroy()
        pending = sum(1 for b in self.bookings if b.get("status")=="PENDING_PAYMENT")
        paid = sum(1 for b in self.bookings if b.get("status")=="PAID_AWAITING_CONFIRM")
        confirmed = sum(1 for b in self.bookings if b.get("status")=="CONFIRMED")
        self.stat_pending.configure(text=f"⏳ Pending: {pending}")
        self.stat_paid.configure(text=f"💰 Paid: {paid}")
        self.stat_confirmed.configure(text=f"✅ Confirmed: {confirmed}")
        self.bookings_count_label.configure(text=f"{len(self.bookings)} bookings")
        self.stats_label.configure(text=f"Messages: {self.message_count} | Auto-replies: {self.auto_replies} | Bookings: {len(self.bookings)}")

        if not self.bookings:
            ctk.CTkLabel(self.bookings_scroll, text="No bookings yet. AI will auto-create when a customer inquires.", font=("Segoe UI", 12), text_color="gray").pack(pady=20)
            return
        # sort by created_at desc
        for b in reversed(self.bookings):
            self._booking_card(b)

    def _booking_card(self, b):
        status = b.get("status","")
        color = COLORS["card2"]
        status_color = COLORS["text2"]
        if status=="PENDING_PAYMENT": status_color = COLORS["yellow"]
        elif status=="PAID_AWAITING_CONFIRM": status_color = COLORS["orange"]
        elif status=="CONFIRMED": status_color = COLORS["green"]
        elif status=="CANCELLED": status_color = COLORS["red"]

        card = ctk.CTkFrame(self.bookings_scroll, fg_color=color, corner_radius=8, border_width=1, border_color=COLORS["border"])
        card.pack(fill="x", pady=4, padx=2)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8,2))
        ctk.CTkLabel(top, text=f"{b.get('id','')}  •  {b.get('date','')}  •  {b.get('tour_type','')}", font=("Segoe UI", 9, "bold"), text_color=COLORS["text"]).pack(side="left")
        ctk.CTkLabel(top, text=status, font=("Segoe UI", 8, "bold"), text_color=status_color).pack(side="right")

        mid = ctk.CTkFrame(card, fg_color="transparent")
        mid.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(mid, text=f"👤 {b.get('customer_name','')}  |  📞 {b.get('contact','')}  |  👥 {b.get('pax','')} pax  |  FB:{b.get('customer_fb_id','')[:10]}", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w")
        ctk.CTkLabel(mid, text=f"💵 Price P{b.get('price','')}  |  Down P{b.get('downpayment','')}  |  GCash Ref: {b.get('gcash_ref','-')}", font=("Consolas", 11), text_color=COLORS["text2"]).pack(anchor="w")
        ctk.CTkLabel(mid, text=f"Created: {b.get('created_at','')}", font=("Segoe UI", 10), text_color="gray").pack(anchor="w")

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=(4,8))
        if status=="PENDING_PAYMENT":
            ctk.CTkButton(btns, text="💰 Mark Paid", width=80, height=32, font=("Segoe UI", 7, "bold"), fg_color=COLORS["orange"], command=lambda bid=b["id"]: self._update_booking_status(bid, "PAID_AWAITING_CONFIRM")).pack(side="left", padx=2)
        if status=="PAID_AWAITING_CONFIRM":
            ctk.CTkButton(btns, text="✅ Confirm Booking", width=110, height=32, font=("Segoe UI", 7, "bold"), fg_color=COLORS["green2"], command=lambda bid=b["id"]: self._update_booking_status(bid, "CONFIRMED")).pack(side="left", padx=2)
        if status not in ["CANCELLED","CONFIRMED"]:
            ctk.CTkButton(btns, text="❌ Cancel", width=70, height=32, font=("Segoe UI", 10), fg_color=COLORS["card"], border_width=1, border_color=COLORS["red"], text_color=COLORS["red"], command=lambda bid=b["id"]: self._update_booking_status(bid, "CANCELLED")).pack(side="left", padx=2)
        if status=="CONFIRMED":
            ctk.CTkButton(btns, text="📩 Send Confirm Msg", width=110, height=32, font=("Segoe UI", 10), fg_color=COLORS["accent2"], command=lambda bid=b["id"]: self._send_confirm_msg(bid)).pack(side="left", padx=2)

    def _update_booking_status(self, bid, new_status):
        for b in self.bookings:
            if b["id"]==bid:
                b["status"]=new_status
                b["updated_at"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_bookings()
                self.refresh_bookings()
                self.log(f"📅 Booking {bid} → {new_status}")
                # if confirmed, send auto message to customer if possible
                if new_status=="CONFIRMED":
                    self.log(f"  → Pwede na i-click 'Send Confirm Msg' para auto-notify customer")
                break

    def _send_confirm_msg(self, bid):
        for b in self.bookings:
            if b["id"]==bid:
                msg = f"✅ CONFIRMED! Hi {b['customer_name']}, confirmed na po booking nyo sa {b['date']} ({b['tour_type']}, {b['pax']} pax). Price P{b['price']}. Kitakits po sa Calatagan! Contact {self.config_data['business_info']['contact']} kung may tanong."
                ok = self.send_facebook_message(b["customer_fb_id"], msg)
                if ok:
                    self.log(f"✓ Confirm message sent to {b['customer_name']}")
                else:
                    messagebox.showinfo("Preview", f"Message (hindi na-send, no token):\n\n{msg}")
                break

    def check_avail_ui(self):
        d = self.avail_entry.get().strip()
        if not d:
            return
        avail, booked = self.check_availability(d)
        if avail:
            self.avail_result.configure(text=f"✅ Available ang {d}", text_color=COLORS["green"])
        else:
            if booked.get("blocked"):
                self.avail_result.configure(text=f"🚫 Blocked {d}: {booked.get('reason','')}", text_color=COLORS["red"])
            else:
                self.avail_result.configure(text=f"❌ Taken na {d} by {booked.get('customer_name','')} ({booked.get('id','')})", text_color=COLORS["red"])

    # ---------- VACATION & BLOCKED UI ----------
    def _vac_text(self):
        if self.config_data.get("vacation_enabled"):
            u = self.config_data.get("vacation_until","")
            r = self.config_data.get("vacation_reason","Vacation")
            return f"ON until {u} ({r})" if u else f"ON ({r})"
        return "OFF"

    def toggle_vacation(self):
        enabled = self.vac_var.get() == "on"
        self.config_data["vacation_enabled"] = enabled
        self.save_config()
        self.vac_switch.configure(text_color=COLORS["red"] if enabled else COLORS["text2"])
        self.vac_label.configure(text=self._vac_text())
        self.refresh_blocked()
        self.log(f"{'🏖 Vacation ON' if enabled else '🏖 Vacation OFF'} {self._vac_text()}")

    def set_vacation(self):
        win = ctk.CTkToplevel(self)
        win.title("Vacation Mode")
        win.geometry("420x350")
        win.configure(fg_color=COLORS["card"])
        win.transient(self); win.grab_set()
        ctk.CTkLabel(win, text="🏖 Set Vacation / Emergency Close", font=("Segoe UI", 13, "bold"), text_color=COLORS["accent"]).pack(pady=12)
        ctk.CTkLabel(win, text="Until Date (YYYY-MM-DD, blank = indefinite)", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=20)
        until_e = ctk.CTkEntry(win, width=380, height=34)
        until_e.pack(padx=20, pady=6)
        until_e.insert(0, self.config_data.get("vacation_until",""))
        ctk.CTkLabel(win, text="Reason", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=20)
        reason_e = ctk.CTkEntry(win, width=380, height=34)
        reason_e.pack(padx=20, pady=6)
        reason_e.insert(0, self.config_data.get("vacation_reason","Vacation - may bagyo"))
        reasons = ["Vacation","Bagyo / Typhoon","Emergency","Maintenance","Closed"]
        def pick(r):
            reason_e.delete(0,"end"); reason_e.insert(0,r)
        rf = ctk.CTkFrame(win, fg_color="transparent")
        rf.pack(fill="x", padx=20, pady=4)
        for r in reasons:
            ctk.CTkButton(rf, text=r, width=75, height=24, font=("Segoe UI", 8), fg_color=COLORS["card2"], command=lambda x=r: pick(x)).pack(side="left", padx=2)
        def save():
            self.config_data["vacation_until"] = until_e.get().strip()
            self.config_data["vacation_reason"] = reason_e.get().strip() or "Vacation"
            self.config_data["vacation_enabled"] = True
            self.vac_var.set("on")
            self.save_config()
            self.vac_switch.configure(text_color=COLORS["red"])
            self.vac_label.configure(text=self._vac_text())
            self.refresh_blocked()
            self.log(f"🏖 Vacation set until {until_e.get().strip()} reason {reason_e.get().strip()}")
            win.destroy()
            messagebox.showinfo("Vacation Set", f"Vacation ON: {self._vac_text()}\nAI will auto-reply closed.")
        ctk.CTkButton(win, text="✅ Enable Vacation", fg_color=COLORS["red"], hover_color="#cc0033", command=save).pack(pady=12, padx=20, fill="x")
        ctk.CTkButton(win, text="❌ Disable Vacation", fg_color=COLORS["card2"], command=lambda: (self.config_data.update({"vacation_enabled": False}), self.vac_var.set("off"), self.save_config(), self.vac_label.configure(text=self._vac_text()), self.vac_switch.configure(text_color=COLORS["text2"]), self.refresh_blocked(), win.destroy())).pack(padx=20, fill="x")
        ctk.CTkButton(win, text="Cancel", fg_color="transparent", border_width=1, border_color=COLORS["border"], text_color=COLORS["text2"], command=win.destroy).pack(pady=6, padx=20, fill="x")

    def block_dates_popup(self):
        win = ctk.CTkToplevel(self)
        win.title("Block Dates")
        win.geometry("440x400")
        win.configure(fg_color=COLORS["card"])
        win.transient(self); win.grab_set()
        ctk.CTkLabel(win, text="🚫 Block Date Range", font=("Segoe UI", 13, "bold"), text_color=COLORS["accent"]).pack(pady=12)
        ctk.CTkLabel(win, text="Start Date (YYYY-MM-DD)", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=20)
        s_e = ctk.CTkEntry(win, width=400, height=34, placeholder_text="2026-09-10")
        s_e.pack(padx=20, pady=4)
        ctk.CTkLabel(win, text="End Date (YYYY-MM-DD)", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=20)
        e_e = ctk.CTkEntry(win, width=400, height=34, placeholder_text="2026-09-15")
        e_e.pack(padx=20, pady=4)
        ctk.CTkLabel(win, text="Reason", font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=20)
        r_e = ctk.CTkEntry(win, width=400, height=34, placeholder_text="Bagyo / Vacation / Emergency")
        r_e.pack(padx=20, pady=4)
        r_e.insert(0, "Bagyo")
        reasons = ["Bagyo","Vacation","Emergency","Maintenance"]
        rf = ctk.CTkFrame(win, fg_color="transparent")
        rf.pack(fill="x", padx=20, pady=4)
        for r in reasons:
            ctk.CTkButton(rf, text=r, width=80, height=24, font=("Segoe UI", 8), fg_color=COLORS["card2"], command=lambda x=r: (r_e.delete(0,"end"), r_e.insert(0,x))).pack(side="left", padx=2)
        def save():
            import datetime as _dt
            s = s_e.get().strip()
            e = e_e.get().strip() or s
            reason = r_e.get().strip() or "Blocked"
            try:
                _dt.datetime.strptime(s, "%Y-%m-%d")
                _dt.datetime.strptime(e, "%Y-%m-%d")
                if s > e: raise ValueError("Start > End")
            except Exception as ex:
                messagebox.showwarning("Date error", f"Use YYYY-MM-DD format.\n{ex}")
                return
            data = self.load_blocked_dates()
            data.append({"id": f"BLK{int(time.time())%100000:05d}", "start": s, "end": e, "reason": reason, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            self.save_blocked_dates(data)
            self.refresh_blocked()
            self.log(f"🚫 Blocked {s} to {e} ({reason})")
            win.destroy()
            messagebox.showinfo("Blocked", f"Blocked {s} → {e}\nReason: {reason}")
        ctk.CTkButton(win, text="✅ Block Range", fg_color=COLORS["red"], hover_color="#cc0033", command=save).pack(pady=12, padx=20, fill="x")
        ctk.CTkButton(win, text="Cancel", fg_color=COLORS["card2"], command=win.destroy).pack(padx=20, fill="x")

    def refresh_blocked(self):
        try:
            for w in self.blocked_frame.winfo_children():
                w.destroy()
            # vacation banner
            is_vac, reason = self.is_vacation_active()
            if is_vac:
                ctk.CTkLabel(self.blocked_frame, text=f"🏖 VACATION ON: {reason} — {self._vac_text()}  (AI says closed)", font=("Segoe UI", 10, "bold"), text_color=COLORS["red"]).pack(anchor="w", padx=6, pady=2)
            data = self.load_blocked_dates()
            if not data and not is_vac:
                ctk.CTkLabel(self.blocked_frame, text="🚫 Blocked Dates: none — click 🚫 Block Dates to add", font=("Consolas", 10), text_color="gray").pack(anchor="w", padx=6, pady=4)
                return
            for blk in data:
                row = ctk.CTkFrame(self.blocked_frame, fg_color=COLORS["card2"], corner_radius=6)
                row.pack(fill="x", padx=4, pady=2)
                ctk.CTkLabel(row, text=f"🚫 {blk.get('start','')} → {blk.get('end','')}  ({blk.get('reason','')})  [{blk.get('id','')}]", font=("Consolas", 10), text_color=COLORS["yellow"]).pack(side="left", padx=8, pady=4)
                ctk.CTkButton(row, text="✕ Unblock", width=70, height=24, font=("Segoe UI", 8), fg_color=COLORS["card"], border_width=1, border_color=COLORS["red"], text_color=COLORS["red"], command=lambda bid=blk["id"]: self.unblock_date(bid)).pack(side="right", padx=6)
        except Exception as e:
            self.log(f"blocked refresh error: {e}")

    def unblock_date(self, bid):
        data = [b for b in self.load_blocked_dates() if b.get("id") != bid]
        self.save_blocked_dates(data)
        self.refresh_blocked()
        self.log(f"✅ Unblocked {bid}")

    def manual_add_booking(self):
        # simple popup via messagebox + entry? Use toplevel
        win = ctk.CTkToplevel(self)
        win.title("Manual Add Booking")
        win.geometry("400x420")
        win.configure(fg_color=COLORS["card"])
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="Manual Add Booking (blocked date)", font=("Segoe UI", 14, "bold"), text_color=COLORS["accent"]).pack(pady=10)
        entries = {}
        for label, key in [("Date (YYYY-MM-DD or Aug 30)","date"),("Customer Name","customer_name"),("Contact","contact"),("Pax","pax"),("Tour Type","tour_type")]:
            ctk.CTkLabel(win, text=label, font=("Segoe UI", 11), text_color=COLORS["text2"]).pack(anchor="w", padx=20, pady=(6,0))
            e = ctk.CTkEntry(win, width=360, height=34)
            e.pack(padx=20, pady=2)
            if key=="tour_type": e.insert(0, "Day Tour")
            if key=="pax": e.insert(0, "15")
            entries[key]=e
        def save():
            b = {
                "id": f"BK{int(time.time())%100000:05d}",
                "customer_fb_id": "MANUAL",
                "customer_name": entries["customer_name"].get().strip() or "Blocked",
                "contact": entries["contact"].get().strip(),
                "date": entries["date"].get().strip(),
                "tour_type": entries["tour_type"].get().strip(),
                "pax": entries["pax"].get().strip(),
                "price": self.config_data["business_info"].get("price_day_amount","3500"),
                "downpayment": self.config_data["business_info"].get("downpayment","1000"),
                "gcash_number": self.config_data["business_info"].get("gcash_number",""),
                "gcash_name": self.config_data["business_info"].get("gcash_name",""),
                "status": "CONFIRMED",
                "gcash_ref": "MANUAL_BLOCK",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if not b["date"]:
                messagebox.showwarning("Error","Lagay ng date!")
                return
            self.bookings.append(b)
            self.save_bookings()
            self.refresh_bookings()
            self.log(f"📅 Manual blocked: {b['date']} -> CONFIRMED")
            win.destroy()
        ctk.CTkButton(win, text="Save Booking", fg_color=COLORS["green2"], command=save).pack(pady=16)
        ctk.CTkButton(win, text="Cancel", fg_color=COLORS["card2"], command=win.destroy).pack()

    # ---------- DASHBOARD ----------
    def get_dashboard_stats(self):
        biz = self.config_data.get("business_info",{})
        try: price = int(re.sub(r"\D","", str(biz.get("price_day_amount","3500"))) or 3500)
        except: price = 3500
        try: down = int(re.sub(r"\D","", str(biz.get("downpayment","1000"))) or 1000)
        except: down = 1000
        total = len(self.bookings)
        confirmed = sum(1 for b in self.bookings if b.get("status")=="CONFIRMED")
        paid = sum(1 for b in self.bookings if b.get("status")=="PAID_AWAITING_CONFIRM")
        pending = sum(1 for b in self.bookings if b.get("status")=="PENDING_PAYMENT")
        inquiry = sum(1 for b in self.bookings if b.get("status")=="INQUIRY")
        cancelled = sum(1 for b in self.bookings if b.get("status")=="CANCELLED")
        revenue_confirmed = confirmed * price
        revenue_paid = paid * down
        revenue_total = revenue_confirmed + revenue_paid
        from collections import Counter
        dates = Counter(b.get("date","") for b in self.bookings if b.get("date") and b.get("status") not in ["CANCELLED"])
        peak_date, peak_count = dates.most_common(1)[0] if dates else ("-",0)
        total_pax = 0
        for b in self.bookings:
            try: total_pax += int(re.search(r"\d+", str(b.get("pax","0"))).group(0))
            except: pass
        monthly = Counter()
        for b in self.bookings:
            try:
                d = b.get("created_at","")[:7]
                if d: monthly[d] += 1
            except: pass
        # all balsas total
        all_total = sum(len(json.load(open(resource_path(f"bookings_{c['id']}.json"), encoding="utf-8"))) if os.path.exists(resource_path(f"bookings_{c['id']}.json")) else 0 for c in self.clients)
        return {"total": total, "confirmed": confirmed, "paid": paid, "pending": pending, "inquiry": inquiry, "cancelled": cancelled, "revenue_confirmed": revenue_confirmed, "revenue_paid": revenue_paid, "revenue_total": revenue_total, "peak_date": peak_date, "peak_count": peak_count, "total_pax": total_pax, "monthly": dict(monthly), "price": price, "down": down, "all_total": all_total}

    def refresh_dashboard(self):
        try: self.dash_balsa_label.configure(text=f"— {self.get_active_client()['name']} ({len(self.clients)} balsas)")
        except: pass
        stats = self.get_dashboard_stats()
        # cards
        for w in self.dash_cards_frame.winfo_children(): w.destroy()
        cards = [
            ("Total", str(stats["total"]), COLORS["accent2"]),
            ("✅ Confirmed", str(stats["confirmed"]), COLORS["green"]),
            ("💰 Paid", str(stats["paid"]), COLORS["orange"]),
            ("⏳ Pending", str(stats["pending"]), COLORS["yellow"]),
            ("❓ Inquiry", str(stats["inquiry"]), COLORS["text2"]),
            ("❌ Cancelled", str(stats["cancelled"]), COLORS["red"]),
        ]
        for label, val, col in cards:
            card = ctk.CTkFrame(self.dash_cards_frame, fg_color=COLORS["card2"], corner_radius=10, border_width=1, border_color=COLORS["border"], width=110, height=70)
            card.pack(side="left", padx=4, pady=4)
            card.pack_propagate(False)
            ctk.CTkLabel(card, text=val, font=("Segoe UI", 16, "bold"), text_color=col).pack(pady=(8,0))
            ctk.CTkLabel(card, text=label, font=("Segoe UI", 9), text_color=COLORS["text2"]).pack()
        self.dash_revenue_label.configure(text=f"💰 Revenue — Confirmed P{stats['revenue_confirmed']:,} + Down P{stats['revenue_paid']:,} = Total P{stats['revenue_total']:,}  (price P{stats['price']:,} / down P{stats['down']:,})")
        self.dash_peak_label.configure(text=f"🔥 Peak Date: {stats['peak_date']} ({stats['peak_count']} bookings)")
        self.dash_pax_label.configure(text=f"👥 Total Pax (all bookings): {stats['total_pax']}  |  All Balsas Total Bookings: {stats['all_total']}")
        monthly_str = ", ".join([f"{k}:{v}" for k,v in sorted(stats["monthly"].items())[-6:]]) or "wala pa"
        self.dash_monthly_label.configure(text=f"📅 Monthly (last 6): {monthly_str}")
        # also update bookings tab badge
        try: self.refresh_bookings()
        except: pass
        self.log(f"📊 Dashboard refreshed — Total {stats['total']} | Revenue P{stats['revenue_total']:,}")

    def export_dashboard_csv(self):
        try:
            import csv
            path = resource_path(f"dashboard_{self.active_client_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["id","customer_name","contact","date","pax","tour_type","status","price","gcash_ref","created_at"])
                for b in self.bookings:
                    w.writerow([b.get("id",""), b.get("customer_name",""), b.get("contact",""), b.get("date",""), b.get("pax",""), b.get("tour_type",""), b.get("status",""), b.get("price",""), b.get("gcash_ref",""), b.get("created_at","")])
            messagebox.showinfo("Exported", f"CSV saved:\n{path}")
            self.log(f"📤 Dashboard CSV exported: {path}")
        except Exception as e:
            messagebox.showerror("Export error", str(e))

    # ---------- AUTO-REMINDER + REVIEW ----------
    def parse_booking_date_local(self, date_str):
        if not date_str: return None
        import datetime as _dt
        s = str(date_str).strip().lower()
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            try: return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except: pass
        m = re.match(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", s)
        if m:
            try:
                mm, dd = int(m.group(1)), int(m.group(2))
                yy = m.group(3)
                y = int(yy) if yy else _dt.date.today().year
                if y < 100: y += 2000
                return _dt.date(y, mm, dd)
            except: pass
        months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
        for k,v in months.items():
            mm = re.search(k + r"\s*(\d{1,2})", s)
            if mm:
                try:
                    d = int(mm.group(1))
                    now = _dt.date.today()
                    y = now.year
                    try:
                        cand = _dt.date(y, v, d)
                        if cand < now: cand = _dt.date(y+1, v, d)
                        return cand
                    except: return _dt.date(y, v, d)
                except: pass
        return None

    def run_reminders_and_reviews_local(self):
        import datetime as _dt
        today = _dt.date.today()
        tomorrow = today + _dt.timedelta(days=1)
        yesterday = today - _dt.timedelta(days=1)
        biz = self.config_data.get("business_info",{})
        changed = False
        for b in self.bookings:
            if b.get("status") not in ["CONFIRMED","PAID_AWAITING_CONFIRM"]: continue
            fb_id = b.get("customer_fb_id","")
            if not fb_id or fb_id=="MANUAL" or not fb_id.isdigit(): continue
            bdate = self.parse_booking_date_local(b.get("date",""))
            if not bdate: continue
            if bdate == tomorrow and not b.get("reminder_sent"):
                msg = f"Hi {b.get('customer_name','Mam/Sir')}! 👋 Reminder lang po — bukas na ({b.get('date')}) ang Day Tour nyo sa {biz.get('name','')} ({b.get('pax','')} pax, 7am-4pm). Kitakits! 🌊 Contact {biz.get('contact','')}."
                ok = self.send_facebook_message(fb_id, msg)
                if ok:
                    b["reminder_sent"]=True
                    b["reminder_sent_at"]=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    changed=True
                    self.log(f"⏰ Reminder sent to {b.get('customer_name')} {b.get('date')}")
            if bdate == yesterday and not b.get("review_sent"):
                msg2 = f"Salamat {b.get('customer_name','Mam/Sir')} sa pagbisita sa {biz.get('name','')} kahapon! 🙏 Review naman po sa FB page ⭐ Balik kayo! 🌊"
                ok2 = self.send_facebook_message(fb_id, msg2)
                if ok2:
                    b["review_sent"]=True
                    b["review_sent_at"]=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    changed=True
                    self.log(f"⭐ Review request sent to {b.get('customer_name')}")
        if changed:
            self.save_bookings()
            try: self.after(0, self.refresh_bookings)
            except: pass
            try: self.after(0, self.refresh_dashboard)
            except: pass

    def _start_reminder_loop(self):
        def _loop():
            time.sleep(60)
            while True:
                try: self.run_reminders_and_reviews_local()
                except Exception as e: self.log(f"[REMINDER] loop error: {e}")
                time.sleep(3600)
        threading.Thread(target=_loop, daemon=True).start()
        self.log("⏰ Auto-Reminder+Review loop started (hourly)")

    def manual_trigger_reminders(self):
        self.log("⏰ Manual trigger reminders/reviews...")
        self.run_reminders_and_reviews_local()
        messagebox.showinfo("Reminders", "Checked reminders & review requests — tingnan ang log.")

    # ---------- GCASH SCREENSHOT AUTO-VERIFY ----------
    def verify_gcash_image_local(self, image_path):
        """Verify GCash screenshot via Gemini Vision (desktop). Returns dict or None."""
        try:
            import base64
            with open(image_path, "rb") as f:
                img_bytes = f.read()
            biz = self.config_data.get("business_info",{})
            api_key = self.config_data.get("ai_api_key","")
            if not api_key:
                messagebox.showwarning("No AI Key", "Lagay muna Gemini API Key sa config para magamit ang auto-verify.")
                return None
            self.log(f"🔍 Verifying GCash screenshot: {os.path.basename(image_path)} ({len(img_bytes)} bytes)...")
            # try Gemini vision via google.genai
            prompt = (
                "You are a GCash receipt OCR. Extract from this GCash screenshot:\n"
                "- Reference Number (9-13 digits)\n"
                "- Amount (e.g., 1000.00)\n"
                "- Date/Time if visible\n"
                "Return ONLY JSON: {\"ref\":\"...\", \"amount\":\"...\", \"date\":\"...\", \"confident\": true/false}\n"
                f"Expected GCash receiver: {biz.get('gcash_number','')} ({biz.get('gcash_name','')}), expected down {biz.get('downpayment','1000')}."
            )
            keys = [k.strip() for k in api_key.split(",") if k.strip()]
            import re as _re, json as _js
            for key in keys:
                try:
                    from google import genai as genai_new
                    from google.genai import types
                    client_ai = genai_new.Client(api_key=key)
                    for mdl in ["gemini-2.5-flash", "gemini-flash-latest", "gemini-1.5-flash"]:
                        try:
                            resp = client_ai.models.generate_content(
                                model=mdl,
                                contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt), types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")])]
                            )
                            txt = (resp.text or "").strip()
                            m = _re.search(r"\{.*?\}", txt, _re.S)
                            if m:
                                j = _js.loads(m.group(0))
                                if j.get("ref"):
                                    self.log(f"✓ GCash Vision ({mdl}) Ref={j.get('ref')} Amt={j.get('amount')}")
                                    return j
                        except Exception as me:
                            self.log(f"  vision {mdl} fail: {me}")
                            continue
                except Exception as e:
                    self.log(f"  genai error: {e}")
                # REST fallback
                try:
                    import requests, base64 as _b64
                    b64 = _b64.b64encode(img_bytes).decode()
                    for mdl in ["gemini-1.5-flash"]:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={key}"
                        payload = {"contents":[{"role":"user","parts":[{"text":prompt},{"inline_data":{"mime_type":"image/jpeg","data":b64}}]}]}
                        r = requests.post(url, json=payload, timeout=15)
                        if r.status_code==200:
                            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                            m = _re.search(r"\{.*?\}", txt, _re.S)
                            if m:
                                j = _js.loads(m.group(0))
                                if j.get("ref"): return j
                except: pass
            # fallback regex if AI fails - just guess digits
            m = _re.search(r"(\d{9,13})", prompt)
            self.log("✗ GCash vision failed — pakisend manual Ref na lang")
            return None
        except Exception as e:
            self.log(f"✗ GCash verify error: {e}")
            return None

    def upload_gcash_screenshot(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Select GCash Screenshot", filetypes=[("Images","*.png;*.jpg;*.jpeg"),("All","*.*")])
        if not path: return
        res = self.verify_gcash_image_local(path)
        if res and res.get("ref"):
            import re as _re2
            ref = _re2.sub(r"\D","", str(res.get("ref","")))
            amt = res.get("amount","")
            msg = f"GCash Verified!\nRef: {ref}\nAmount: {amt}\nConfident: {res.get('confident',False)}\n\nI-auto-mark ko sa latest PENDING booking kung meron."
            if messagebox.askyesno("GCash Verified", msg + "\n\nAuto-mark as PAID?"):
                booked = self.mark_paid(self.sim_sender, ref)
                if not booked:
                    # find latest pending any
                    for b in reversed(self.bookings):
                        if b.get("status") in ["PENDING_PAYMENT","INQUIRY"]:
                            booked = b
                            b["gcash_ref"] = ref
                            b["gcash_amount"] = amt
                            b["status"] = "PAID_AWAITING_CONFIRM"
                            b["paid_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            self.save_bookings()
                            self.refresh_bookings()
                            break
                if booked:
                    messagebox.showinfo("Marked Paid", f"Booking {booked['id']} → PAID_AWAITING_CONFIRM Ref:{ref}")
                else:
                    messagebox.showinfo("No booking", "Walang pending booking na ma-match. Save Ref na lang.")
        else:
            messagebox.showwarning("No Ref", "Hindi ma-extract ang Ref. Pakisend manual na lang ang 13-digit Ref.")

    # ---------- FLASK ----------
    def _init_flask(self):
        if not FLASK_AVAILABLE:
            self.log("✗ Flask not installed! Run: pip install Flask")
            return
        self.flask_app = Flask(__name__)

        @self.flask_app.route("/", methods=["GET"])
        def index():
            return jsonify({"status": "CCPT Bot v2 Running", "auto_reply": self.config_data.get("auto_reply_enabled"), "messages": self.message_count, "bookings": len(self.bookings)})

        @self.flask_app.route("/health", methods=["GET"])
        def health():
            return jsonify({"ok": True, "auto_reply": self.config_data.get("auto_reply_enabled")})

        @self.flask_app.route("/webhook", methods=["GET"])
        def verify():
            mode = flask_request.args.get("hub.mode")
            token = flask_request.args.get("hub.verify_token")
            challenge = flask_request.args.get("hub.challenge")
            expected = self.config_data.get("verify_token","mqs_verify_2026")
            if mode == "subscribe" and token == expected:
                self.log(f"✓ Webhook verified! Challenge: {challenge}")
                self.after(0, lambda: self._set_status(True, "Webhook Verified ✓"))
                return challenge, 200
            else:
                self.log(f"✗ Webhook verify failed. Got token: {token}, expected: {expected}")
                return "Verification failed", 403

        @self.flask_app.route("/webhook", methods=["POST"])
        def webhook():
            try:
                data = flask_request.get_json()
                self.log(f"📩 Incoming webhook: {json.dumps(data)[:300]}")
                if data.get("object") == "page":
                    for entry in data.get("entry", []):
                        for event in entry.get("messaging", []):
                            sender_id = event.get("sender",{}).get("id")
                            msg = event.get("message",{})
                            text = msg.get("text","")
                            # route to correct balsa by page_id (for multi-client)
                            page_id = entry.get("id","")
                            target_client = self.get_client_by_page_id(page_id)
                            target_cfg = target_client["config"] if target_client else self.config_data
                            # handle image attachments (GCash proof) - desktop local
                            attach = msg.get("attachments",[])
                            if attach and any(a.get("type")=="image" for a in attach):
                                # try GCash vision locally if possible (download if url)
                                try:
                                    img_att = next(a for a in attach if a.get("type")=="image")
                                    img_url = img_att.get("payload",{}).get("url","")
                                    if img_url and self.config_data.get("ai_api_key"):
                                        import requests as _rq, threading as _th
                                        def _verify_async(url, sid, cli):
                                            try:
                                                r = _rq.get(url, timeout=10)
                                                if r.status_code==200:
                                                    # save temp and verify
                                                    import tempfile, os as _os
                                                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tf:
                                                        tf.write(r.content)
                                                        tp = tf.name
                                                    self.log(f"🖼 GCash image from {sid}, verifying...")
                                                    # reuse verify logic via file
                                                    res = self.verify_gcash_image_local(tp)
                                                    try: _os.remove(tp)
                                                    except: pass
                                                    if res and res.get("ref"):
                                                        ref = res.get("ref")
                                                        # mark paid if possible
                                                        try:
                                                            b = self.mark_paid(sid, str(ref))
                                                            if b:
                                                                self.send_facebook_message(sid, f"Salamat po! 🙏 Na-verify GCash Ref: {ref} Amount: {res.get('amount','')} — PAID na, confirm ni owner. 🎉")
                                                            else:
                                                                self.send_facebook_message(sid, f"Salamat! Ref {ref} na-receive, i-forward ko kay owner.")
                                                        except: pass
                                            except Exception as e:
                                                self.log(f"  image verify thread error: {e}")
                                        _th.Thread(target=_verify_async, args=(img_url, sender_id, target_client), daemon=True).start()
                                        text = f"GCash screenshot Ref auto-verify"
                                    else:
                                        text = "GCash screenshot proof"
                                except: text = "GCash screenshot proof"
                            elif attach and not text:
                                text = "GCash screenshot proof"
                            if sender_id and text:
                                self.message_count += 1
                                self.after(0, lambda: self._update_stats())
                                self.after(0, lambda t=text, s=sender_id: self.log(f"👤 User {s}: {t}"))
                                # if message belongs to different balsa, handle with that client's context
                                if target_client and target_client["id"] != self.active_client_id:
                                    threading.Thread(target=self.handle_message_routed, args=(sender_id, text, target_client), daemon=True).start()
                                else:
                                    threading.Thread(target=self.handle_message, args=(sender_id, text), daemon=True).start()
                return "EVENT_RECEIVED", 200
            except Exception as e:
                self.log(f"✗ Webhook error: {e}")
                return "ERROR", 500

    def _set_status(self, running, msg):
        self.server_running = running
        color = COLORS["green"] if running else COLORS["red"]
        self.status_dot.configure(text_color=color)
        self.status_label.configure(text=f"Server: {msg} (port {self.config_data.get('port',5000)})")
        if running:
            self.webhook_label.configure(text=f"http://localhost:{self.config_data.get('port',5000)}/webhook  → use ngrok for public URL")

    def _update_stats(self):
        self.stats_label.configure(text=f"Messages: {self.message_count} | Auto-replies: {self.auto_replies} | Bookings: {len(self.bookings)}")

    def start_server(self):
        if not FLASK_AVAILABLE:
            self._set_status(False, "Flask missing")
            return
        if self.flask_thread and self.flask_thread.is_alive():
            return
        port = int(self.config_data.get("port",5000))
        def run():
            try:
                self.after(0, lambda: self._set_status(True, "Running ✓"))
                self.after(0, lambda: self.log(f"✓ Server started on port {port}"))
                self.after(0, lambda: self.log(f"  Local webhook: http://localhost:{port}/webhook"))
                self.flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
            except OSError as e:
                self.after(0, lambda: self.log(f"✗ Port {port} busy: {e}"))
                self.after(0, lambda: self._set_status(False, f"Port {port} busy!"))
            except Exception as e:
                self.after(0, lambda: self.log(f"✗ Server error: {e}"))
                self.after(0, lambda: self._set_status(False, "Error"))
        self.flask_thread = threading.Thread(target=run, daemon=True)
        self.flask_thread.start()

    def restart_server(self):
        self.log("↻ Restarting... Isara at buksan ulit app para mag-apply Port change.")
        messagebox.showinfo("Restart", "Isara at buksan ulit ang app para mag-apply ang bagong Port.\nToken/AI changes - no need restart.")

    # ---------- AI + BOOKING LOGIC ----------
    def build_system_prompt(self):
        biz = self.config_data.get("business_info",{})
        template = self.config_data.get("ai_system_prompt", DEFAULT_CONFIG["ai_system_prompt"])
        try:
            return template.format(**biz)
        except: return template

    def extract_booking_info(self, text, session):
        """Extract date, pax, name, contact from text using simple rules + update session."""
        t = text.lower()
        # date patterns: 2026-08-30, 08/30, Aug 30, Agosto 30, etc - simple capture
        date_patterns = [
            r"(\d{4}-\d{1,2}-\d{1,2})",
            r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
            r"(aug(?:ust)?\s*\d{1,2})",
            r"(sept?\s*\d{1,2})",
            r"(oct\s*\d{1,2})",
            r"(nov\s*\d{1,2})",
            r"(dec\s*\d{1,2})",
            r"(jan\s*\d{1,2})",
            r"(feb\s*\d{1,2})",
            r"(mar\s*\d{1,2})",
            r"(apr\s*\d{1,2})",
            r"(may\s*\d{1,2})",
            r"(june\s*\d{1,2})",
            r"(july\s*\d{1,2})",
            r"(\d{1,2}\s*ng\s*\w+)",
        ]
        for pat in date_patterns:
            m = re.search(pat, t, re.I)
            if m:
                session["pending_date"] = m.group(1).strip()
                break
        # also check "sa Aug 30" etc, keep last found
        # pax
        m = re.search(r"(\d{1,2})\s*pax", t, re.I)
        if m:
            session["pending_pax"] = m.group(1)
        else:
            m = re.search(r"(\d{1,2})\s*kami", t, re.I)
            if m: session["pending_pax"]=m.group(1)
            else:
                m = re.search(r"(\d{1,2})\s*tao", t, re.I)
                if m: session["pending_pax"]=m.group(1)
        # tour type
        if False and ("night" in t or "overnight" in t):
            session["pending_tour"]="Night Tour"
        elif False and ("22" in t or "22hrs" in t):
            session["pending_tour"]="22 Hours"
        elif "day" in t or "araw" in t or "umaga" in t:
            session["pending_tour"]="Day Tour"
        # contact / phone
        m = re.search(r"09\d{9}", t)
        if m:
            session["pending_contact"]=m.group(0)
        # name: if text has 2 words and no keyword, treat as name? Only if session expects name
        # GCash ref
        m = re.search(r"ref\s*[:#]?\s*(\w+)", t, re.I)
        if m and len(m.group(1))>4:
            session["pending_ref"]=m.group(1)
        elif re.search(r"gcash", t, re.I) and re.search(r"\d{4,}", t):
            m2 = re.search(r"(\d{4,})", t)
            if m2: session["pending_ref"]=m2.group(1)

    def generate_reply(self, sender_id, user_text):
        # session memory
        if sender_id not in self.sessions:
            self.sessions[sender_id] = {"history": [], "pending_date": "", "pending_pax": "", "pending_tour": "Day Tour", "pending_name": "", "pending_contact": "", "pending_ref": ""}
        session = self.sessions[sender_id]
        session["history"].append(f"Customer: {user_text}")
        if len(session["history"])>10:
            session["history"]=session["history"][-10:]

        self.extract_booking_info(user_text, session)

        # Try to extract name if we are at name stage and text looks like name + number
        low = user_text.lower()
        if session.get("pending_date") and session.get("pending_pax") and not session.get("pending_name"):
            # if user sends "Juan 09123456789" -> split
            parts = user_text.strip().split()
            # if first part looks like name and contains no price keywords
            if not any(k in low for k in ["magkano","price","available","pax","day","night","gcash","ref"]):
                # check if has phone
                m = re.search(r"09\d{9}", user_text)
                if m:
                    # remove phone, remaining is name
                    name_part = user_text.replace(m.group(0),"").strip(" ,-")
                    if name_part:
                        session["pending_name"]=name_part
                elif len(parts)>=2 and len(user_text)<30:
                    session["pending_name"]=user_text.strip()

        # Check for GCash ref payment -> mark paid
        if session.get("pending_ref") or ("gcash" in low and "ref" in low) or (re.search(r"\d{6,}", user_text) and "gcash" in low):
            ref = session.get("pending_ref") or re.search(r"(\d{5,})", user_text).group(1) if re.search(r"(\d{5,})", user_text) else "GCashProof"
            # try to mark existing pending booking
            booked = self.mark_paid(sender_id, ref)
            if booked:
                session["history"].append(f"AI: Payment confirmed Ref {ref}")
                # clear pending after paid
                for k in ["pending_date","pending_pax","pending_name","pending_contact","pending_ref"]:
                    session[k]=""
                return f"Salamat po {booked['customer_name']}! 🙏 Na-receive ko Ref: {ref}. Booking nyo sa {booked['date']} ({booked['tour_type']}, {booked['pax']} pax) ay PAID na. I-confirm ni owner sa system at isesend confirmation. Hintay lang po 1-2hrs. Salamat! 🎉"

        # If AI has full info -> confirmation flow + inquiry notify even if no confirm
        biz = self.config_data["business_info"]
        if session.get("pending_date") and session.get("pending_pax") and session.get("pending_name") and session.get("pending_contact"):
            # if awaiting confirmation, handle YES/NO
            if session.get("awaiting_confirm"):
                low2 = user_text.lower().strip()
                if any(k in low2 for k in ["yes", "oo", "sige", "confirm", "tama", "ok na", "go", "yess", "opo", "yes po"]):
                    # confirm -> upgrade inquiry to PENDING_PAYMENT
                    for b in self.bookings:
                        if b.get("id")==session.get("inquiry_id"):
                            b["status"] = "PENDING_PAYMENT"
                            self.save_bookings()
                            try: self.after(0, self.refresh_bookings)
                            except: pass
                            break
                    existing = [b for b in self.bookings if b.get("customer_fb_id")==sender_id and b.get("date")==session["pending_date"] and b.get("status")=="PENDING_PAYMENT"]
                    if not existing:
                        booking = self.create_pending_booking(sender_id, session["pending_date"], session["pending_pax"], session["pending_name"], session["pending_contact"], session.get("pending_tour","Day Tour"))
                    else:
                        booking = existing[0]
                    session["awaiting_confirm"] = False
                    session["history"].append(f"AI: Confirmed {booking['id']}")
                    return f"✅ CONFIRMED! Salamat {session['pending_name']}! Hold na po booking nyo sa {booking['date']} ({booking['pax']} pax) Day Tour P{booking['price']}. Pakibayad Down P{booking['downpayment']} sa GCash {biz.get('gcash_number','')} ({biz.get('gcash_name','')}) then send Ref dito. Na-notify ko na si owner, tatawagan kayo sa {session['pending_contact']} 📞🎉"
                elif any(k in low2 for k in ["no", "hindi", "cancel", "wag", "ayaw", "no po"]):
                    session["awaiting_confirm"] = False
                    return f"Okay po noted, hindi muna i-hold. Pero na-forward ko na inquiry nyo kay owner ({session['pending_name']} {session['pending_date']} {session['pending_pax']} pax, {session['pending_contact']}) — tatawagan nya po kayo. Salamat! 📞"
                else:
                    return f"Pasuyo po {session['pending_name']}, confirm nyo po ba booking sa {session['pending_date']} ({session['pending_pax']} pax) Day Tour P{biz.get('price_day_amount','3500')}? Reply YES para i-hold, or NO kung may babaguhin. Owner will call you at {session['pending_contact']} kahit hindi mag-confirm 😊"
            # first time complete -> check availability/capacity then create INQUIRY and ask confirm
            avail, taken = self.check_availability(session["pending_date"])
            if not avail:
                if taken.get("blocked"):
                    return f"Sorry po, sarado kami sa {session['pending_date']} — {taken.get('reason','blocked')} 🚫. Available po kami sa next open date. Anong ibang date po gusto nyo? 😊"
                return f"Sorry po, taken na ang {session['pending_date']} (na-book na ni {taken.get('customer_name','other guest')} [{taken.get('id','')}]). Available pa po next dates. Anong ibang date po gusto nyo? 😊"
            try:
                pax_num = int(re.search(r"\d+", session["pending_pax"]).group(0))
                cap_nums = re.findall(r"\d+", biz.get("capacity","20"))
                cap_max = int(cap_nums[-1]) if len(cap_nums)>=1 else 20
                if pax_num > cap_max:
                    return f"Paalala lang po, max capacity namin ay {biz.get('capacity','15-20 pax')}. Pag {pax_num} pax, need po ng 2 balsa. Gusto nyo po ba 2 balsa i-book sa {session['pending_date']}? 😊"
            except: pass
            # create INQUIRY immediately so owner gets it even if client doesn't confirm
            inq = self.create_inquiry(sender_id, session["pending_date"], session["pending_pax"], session["pending_name"], session["pending_contact"], session.get("pending_tour","Day Tour"))
            session["awaiting_confirm"] = True
            session["inquiry_id"] = inq["id"]
            return f"Salamat {session['pending_name']}! 🙏 Eto po summary ng napagkasunduan natin:\n\n📅 Date: {session['pending_date']}\n👥 Pax: {session['pending_pax']}\n🏖 Tour: {session.get('pending_tour','Day Tour')} 7am-4pm\n💵 Price: P{biz.get('price_day_amount','3500')}\n💰 Down: P{biz.get('downpayment','1000')} via GCash {biz.get('gcash_number','')} ({biz.get('gcash_name','')})\n📍 {biz.get('location','')} - {biz.get('google_maps_link','')}\n\nTama po ba? Reply YES para i-hold ko booking nyo, or NO kung may babaguhin. Kahit hindi mag-confirm, i-notify ko na si owner para matawagan kayo sa {session['pending_contact']} 📞"

        # Build AI prompt with session context + availability info
        # inject current bookings availability into prompt
        booked_dates = ", ".join([f"{b['date']}({b['status']})" for b in self.bookings[-5:] if b.get("date")])
        booked_info = f"Booked dates (for availability check): {booked_dates if booked_dates else 'wala pa, all dates available'}."
        # Also inject what info we still need
        need = []
        if not session.get("pending_date"): need.append("date")
        elif not session.get("pending_pax"): need.append("pax")
        elif not session.get("pending_name") or not session.get("pending_contact"): need.append("name+contact")
        need_str = ", ".join(need) if need else "complete na, ready to create booking"
        extra_context = f"\nCurrent session for this customer: date={session.get('pending_date','?')}, pax={session.get('pending_pax','?')}, tour={session.get('pending_tour','Day Tour')}, name={session.get('pending_name','?')}, contact={session.get('pending_contact','?')}. Still need: {need_str}. {booked_info}"

        provider = self.config_data.get("ai_provider","gemini")
        api_key = self.config_data.get("ai_api_key","")
        system_prompt = self.build_system_prompt() + extra_context

        # If local or no key -> template with booking awareness
        if provider == "local" or not api_key:
            if not api_key and provider != "local":
                self.log("⚠ No AI Key — template+booking logic mode")
            return self.template_reply_with_booking(user_text, session)

        if provider == "gemini":
            # try new google.genai package first (supports AQ... keys + gemini-3.6-flash)
            try:
                from google import genai as genai_new
                client = genai_new.Client(api_key=api_key)
                history_text = "\n".join(session["history"][-6:])
                prompt = f"{system_prompt}\n\nConversation history:\n{history_text}\n\nLatest customer message: {user_text}\nReply in Tagalog, short, warm, may po:"
                # new model for new keys is gemini-3.6-flash
                for mdl in ["gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash"]:
                    try:
                        resp = client.models.generate_content(model=mdl, contents=prompt)
                        text = (resp.text or "").strip()
                        if text:
                            session["history"].append(f"AI: {text}")
                            self.log(f"✓ Gemini ({mdl}) reply ok")
                            return text
                    except Exception as me:
                        self.log(f"  retry {mdl} fail: {str(me)[:120]}")
                        continue
            except Exception as e:
                self.log(f"  new genai fail: {e}")
            # fallback to old google-generativeai package
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                history_text = "\n".join(session["history"][-6:])
                prompt = f"{system_prompt}\n\nConversation history:\n{history_text}\n\nLatest customer message: {user_text}\nReply (Tagalog, short):"
                for mdl in ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-pro"]:
                    try:
                        model = genai.GenerativeModel(mdl)
                        resp = model.generate_content(prompt)
                        text = (resp.text or "").strip()
                        if text:
                            session["history"].append(f"AI: {text}")
                            return text
                    except: continue
            except Exception as e:
                self.log(f"✗ Gemini error: {e} — fallback template")
                return self.template_reply_with_booking(user_text, session)
            # if all fail
            self.log("✗ Gemini all models failed — fallback template")
            return self.template_reply_with_booking(user_text, session)

        if provider == "openai":
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                msgs = [{"role":"system","content": system_prompt}]
                for h in session["history"][-6:]:
                    role = "user" if h.startswith("Customer:") else "assistant"
                    msgs.append({"role":role,"content": h.split(": ",1)[-1]})
                msgs.append({"role":"user","content": user_text})
                r = client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=260, temperature=0.7)
                text = r.choices[0].message.content.strip()
                session["history"].append(f"AI: {text}")
                return text
            except Exception as e:
                self.log(f"✗ OpenAI error: {e} — fallback template")
                return self.template_reply_with_booking(user_text, session)

        return self.template_reply_with_booking(user_text, session)

    def template_reply_with_booking(self, user_text, session):
        t = user_text.lower()
        biz = self.config_data["business_info"]
        name = biz.get("name","Balsa")
        price_day = biz.get("price_day","3500 (7am-4pm)")
        price_night = biz.get("price_night","WALANG OVERNIGHT - Day Tour lang 7am-4pm")
        capacity = biz.get("capacity","15-20 pax")
        contact = biz.get("contact","09123456789")
        gcash = biz.get("gcash_number","09123456789")
        gcash_name = biz.get("gcash_name","Juan")
        down = biz.get("downpayment","1000")
        inclusions = biz.get("inclusions","Floating cottage, videoke, ihawan, life vest, lutuan")
        maps_link = biz.get("google_maps_link","")
        dti_link = biz.get("dti_permit_url","")
        photos_link = biz.get("balsa_photos_url","")

        # PRIORITY 1: availability check - if user explicitly asks available, answer agad with real check
        if any(k in t for k in ["available", "avail", "bakante", "free"]):
            date_to_check = session.get("pending_date") or ""
            # try extract date from current message if no session date
            if not date_to_check:
                for pat in [r"(\d{4}-\d{1,2}-\d{1,2})", r"(aug\w*\s*\d{1,2})", r"(\d{1,2}/\d{1,2})"]:
                    m = re.search(pat, t, re.I)
                    if m:
                        date_to_check = m.group(1)
                        break
            if date_to_check:
                avail, taken = self.check_availability(date_to_check)
                if avail:
                    return f"✅ Available pa po ang {date_to_check}! 😊 Day {price_day}, Night {price_night}, Capacity {capacity}. Ilan pax po kayo para ma-hold ko booking nyo?"
                else:
                    if taken.get("blocked"):
                        return f"🚫 Sorry po, sarado kami sa {date_to_check} — {taken.get('reason','blocked')}. Next available date po kayo? 😊"
                    return f"❌ Sorry po, taken na ang {date_to_check} ni {taken.get('customer_name','guest')} [{taken.get('id','')}]. Pero available pa next dates. Anong ibang date po gusto nyo?"
            else:
                return f"To check availability, which date would you like? Day {price_day}, Night {price_night} 😊"

        # PRIORITY 2: if we are in booking flow, ask for next missing info
        if session.get("pending_date") and not session.get("pending_pax"):
            return f"Noted po date {session['pending_date']} ({session.get('pending_tour','Day Tour')}) 😊 Ilan pax po kayo? (max {capacity})"
        if session.get("pending_date") and session.get("pending_pax") and (not session.get("pending_name") or not session.get("pending_contact")):
            return f"Got it! {session['pending_date']} - {session['pending_pax']} pax - {session.get('pending_tour','Day Tour')}. Anong pangalan po at contact number para i-hold booking? (ex: Juan 09123456789)"

        if any(k in t for k in ["magkano", "price", "hm ", "how much", "presyo"]):
            return f"Hello po Mam/Sir! 😊 Sa {name}, P{biz.get('price_day_amount','3500')} lang po Day Tour 7am-4pm (WALANG overnight) — kasama na {inclusions}, capacity {capacity}. Location: {biz.get('location','Calatagan')} 📍 Maps: {maps_link}. Anong date po at ilan pax para ma-hold ko booking nyo?"

        # only treat as capacity question if asking (ilan/kasya/capacity) without providing number+pax combo
        if any(k in t for k in ["capacity", "kasya"]) or ("ilan" in t and not re.search(r"\d+\s*pax", t)):
            return f"Capacity po ay {capacity} 😊 Inclusions: {inclusions}. Ilan po kayo at anong date para ma-hold booking?"
        if "pax" in t and re.search(r"\d+\s*pax", t) and not session.get("pending_date"):
            # user gave pax but no date yet, still need date
            return f"Noted {t} pax 😊 Anong date po gusto nyo? Day {price_day}, Night {price_night}"

        # picture / permit / balsa photos
        if any(k in t for k in ["picture", "pic", "photo", "litrato", "itsura", "balsa"]):
            if any(k in t for k in ["dti", "permit", "business permit", "legal"]):
                return f"Opo meron po kaming DTI permit Mam/Sir 😊 Eto po link ng permit namin: {dti_link} — legit po kami. Gusto nyo rin po ba makita actual photos ng balsa? {photos_link} 📸"
            return f"Eto po actual photos ng balsa namin Mam/Sir 📸: {photos_link} — {inclusions} po pala inclusion namin (kasama na sa P{price_day} Day Tour 7am-4pm). Gusto nyo po ba magpa-reserve sa {maps_link}?"
        if any(k in t for k in ["dti", "permit"]):
            return f"Opo legit po kami Mam/Sir — eto po DTI/permit namin: {dti_link} ✅ Pwede nyo po i-check. Location namin {biz.get('location','Calatagan')} — Maps: {maps_link} 📍"

        # inclusion - conversational not just list
        if any(k in t for k in ["inclusion", "kasama", "included"]):
            # get pending name if any for personalization
            nm = session.get("pending_name","Mam/Sir")
            if nm in ["?", "", "Mam/Sir"] : nm = "Mam/Sir"
            return f"Yung inclusion po namin {nm} ay {inclusions} po — yan po lahat kasama na sa P{biz.get('price_day_amount','3500')} Day Tour 7am-4pm sa {name} 😊 May videoke na rin po at lutuan, dala na lang po kayo food. Gusto nyo po ba i-send ko actual photos? {photos_link} 📸"

        # location with maps pin
        if any(k in t for k in ["saan", "location", "san kayo", "address", "maps", "map", "google map", "waze"]):
            return f"📍 Location po namin ay {biz.get('location','Calatagan, Batangas')} — eto po Google Maps pin namin Mam/Sir: {maps_link} — i-pin nyo na lang po sa Waze/Google Maps. Day Tour lang po 7am-4pm. May parking at tindahan po sa tabing dagat. Contact: {contact} 📞"

        # tawad / discount fallback to call
        if any(k in t for k in ["tawad", "discount", "last price", "lp", "mura", "negotiable", "fix na", "tawaran"]):
            return f"Pasensya na po Mam/Sir, fixed na po P{biz.get('price_day_amount','3500')} Day Tour 7am-4pm — sulit na po kasama na {inclusions} 😊 Pero para sure, tawagan nyo na lang po directly si owner sa {contact} — baka may promo pag weekday. Tawag po 7am-9pm 📞"

        # fallback if asking something AI cant answer (detect maybe "hindi" + question)
        # keep original gcash block
        if any(k in t for k in ["gcash", "bayad", "payment", "down"]):
            return f"GCash payment po: {gcash} ({gcash_name}), Downpayment P{down}. After send, pakisend Ref No. dito para auto-confirm booking nyo sa {session.get('pending_date','date nyo')} 😊"

        return f"Hello po! Salamat sa inquiry sa {name} 😊 Day {price_day}, Night {price_night}, Capacity {capacity}. GCash {gcash} ({gcash_name}) Down P{down}. Anong date po, ilan pax, at Day/Night po ba para ma-hold ko booking nyo?"

    def send_facebook_message(self, recipient_id, text):
        token = self.config_data.get("page_access_token","")
        if not token:
            self.log("✗ No Page Token — preview only: " + text[:90])
            return False
        url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
        payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
        try:
            if REQUESTS_AVAILABLE:
                r = requests.post(url, json=payload, timeout=10)
                if r.status_code == 200:
                    self.log(f"✓ Sent to FB {recipient_id}: {text[:60]}...")
                    return True
                else:
                    self.log(f"✗ FB Send failed {r.status_code}: {r.text[:200]}")
                    return False
            else:
                data = json.dumps(payload).encode()
                req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.log(f"✓ Sent to FB: {resp.read().decode()[:100]}")
                    return True
        except Exception as e:
            self.log(f"✗ Send error: {e}")
            return False

    def handle_message(self, sender_id, text):
        if not self.config_data.get("auto_reply_enabled", True):
            self.log(f"⏸ Auto-reply OFF — hindi sinagot: {text[:60]}")
            return
        self.log(f"🤖 Generating reply for {sender_id}: {text[:60]}...")
        reply = self.generate_reply(sender_id, text)
        self.log(f"🤖 AI Reply: {reply}")
        self.send_facebook_message(sender_id, reply)
        self.auto_replies += 1
        self.after(0, lambda: self._update_stats())
        self.after(0, self.refresh_bookings)

    def handle_message_routed(self, sender_id, text, client):
        # handle message for non-active balsa (use its bookings/config but not switch UI)
        # save current, swap, handle, restore
        prev_cfg = self.config_data
        prev_bookings = self.bookings
        prev_id = self.active_client_id
        try:
            self.config_data = client["config"]
            # load that client bookings
            per_path = resource_path(f"bookings_{client['id']}.json")
            if os.path.exists(per_path):
                with open(per_path, 'r', encoding='utf-8') as f:
                    self.bookings = json.load(f)
            else:
                self.bookings = []
            if not self.config_data.get("auto_reply_enabled", True):
                self.log(f"⏸ [{client['name']}] Auto-reply OFF — hindi sinagot: {text[:60]}")
                return
            self.log(f"🤖 [{client['name']}] Generating reply for {sender_id}: {text[:60]}...")
            # generate using client config (generate_reply uses self.config_data)
            reply = self.generate_reply(sender_id + '_' + client['id'], text)  # namespace session per client
            self.log(f"🤖 [{client['name']}] AI Reply: {reply}")
            # send with correct token
            token = client["config"].get("page_access_token","")
            if token:
                url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
                payload = {"recipient": {"id": sender_id}, "message": {"text": reply}}
                try:
                    if REQUESTS_AVAILABLE:
                        r = requests.post(url, json=payload, timeout=10)
                        self.log(f"✓ Sent to FB [{client['name']}] {sender_id}: {reply[:60]}..." if r.status_code==200 else f"✗ FB Send failed {r.status_code}: {r.text[:100]}")
                    else:
                        data = json.dumps(payload).encode()
                        req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
                        urllib.request.urlopen(req, timeout=10)
                except Exception as e:
                    self.log(f"✗ Send error [{client['name']}]: {e}")
            # save bookings for that client
            try:
                with open(per_path, 'w', encoding='utf-8') as f:
                    json.dump(self.bookings, f, indent=4, ensure_ascii=False)
            except: pass
            self.auto_replies += 1
            self.after(0, lambda: self._update_stats())
        finally:
            self.config_data = prev_cfg
            self.bookings = prev_bookings
            self.active_client_id = prev_id

    def test_ai(self):
        txt = self.test_entry.get().strip()
        if not txt:
            txt = "Magkano po balsa?"
            self.test_entry.delete(0,"end")
            self.test_entry.insert(0, txt)
        self.log(f"🧪 TEST [{self.sim_sender}]: {txt}")
        reply = self.generate_reply(self.sim_sender, txt)
        self.log(f"🧪 AI Reply: {reply}")
        messagebox.showinfo("AI Reply Preview", reply)
        self.refresh_bookings()

