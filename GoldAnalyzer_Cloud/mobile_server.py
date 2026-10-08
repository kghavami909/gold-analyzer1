"""
Mobile Web & PWA Server for Gold Analyzer
-----------------------------------------
FastAPI-powered responsive mobile application for real-time gold signals,
ICT Smart Money analytics, MTF trends, and weekly trading archives.
"""

import os
import sys

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
import socket
import threading
import time
from datetime import datetime
import numpy as np
import pytz
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

def sanitize_for_json(obj):
    """تبدیل تمام اشیاء numpy و مقادیر خاص به انواع بومی پایتون جهت جلوگیری از کرش سریالایزر"""
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return [sanitize_for_json(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(v) for v in obj]
    return obj


# افزودن مسیر اصلی به sys.path
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from modules.data_fetcher import get_cached_snapshot, get_full_market_snapshot, fetch_current_price
from modules.signal_generator import generate_signal
from modules.session_analyzer import full_session_report, get_current_session
from modules.weekly_tracker import get_weekly_report, update_weekly_signal_statuses
from modules.ict_analysis import full_ict_report

app = FastAPI(title="Gold Analyzer Mobile")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# داده‌های اشتراکی در حافظه
_STATE = {
    "snapshot": {},
    "signal": {},
    "session": {},
    "last_updated": None,
    "is_loading": False,
    "last_price": None
}

def _background_updater():
    """به‌روزرسانی خودکار داده‌ها در پس‌زمینه هر ۶۰ ثانیه"""
    while True:
        try:
            snap = get_full_market_snapshot()
            utc_now = datetime.now(pytz.UTC)
            sig = generate_signal(snap, utc_time=utc_now)
            sess = full_session_report(snap, utc_now)
            price = (snap.get("current") or {}).get("price")
            
            _STATE["snapshot"] = snap
            _STATE["signal"] = sig
            _STATE["session"] = sess
            _STATE["last_price"] = price
            _STATE["last_updated"] = datetime.now().strftime("%H:%M:%S")
        except Exception as e:
            print(f"[MobileServer Background] Update error: {e}")
        time.sleep(60)

# بارگذاری اولیه از کش
try:
    cached = get_cached_snapshot()
    if cached and not cached.get("gold_1h", None) is None:
        u_now = datetime.now(pytz.UTC)
        _STATE["snapshot"] = cached
        _STATE["signal"] = generate_signal(cached, utc_time=u_now)
        _STATE["session"] = full_session_report(cached, u_now)
        _STATE["last_price"] = (cached.get("current") or {}).get("price")
        _STATE["last_updated"] = datetime.now().strftime("%H:%M:%S")
except Exception as e:
    print(f"[MobileServer] Cache init: {e}")

@app.on_event("startup")
def on_startup():
    threading.Thread(target=_background_updater, daemon=True).start()

def get_network_ips():
    """استخراج تمام IPهای شبکه محلی دستگاه با برچسب تفکیک وای‌فای و وی‌پی‌ان"""
    items = []
    seen = set()

    def add_ip(ip, label):
        if ip and ip not in seen and not ip.startswith("127."):
            seen.add(ip)
            items.append((ip, label))

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip.startswith("192.168.") or (ip.startswith("10.") and not ip.startswith("100.64.")):
                add_ip(ip, "⭐️ [توصیه شده - Wi-Fi/مودم محلی]")
            elif ip.startswith("100.64."):
                add_ip(ip, "(VPN / تونل)")
            elif not ip.startswith("127."):
                add_ip(ip, "(شبکه محلی)")
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(('8.8.8.8', 80))
        primary = s.getsockname()[0]
        s.close()
        if primary and primary not in seen:
            add_ip(primary, "(پیش‌فرض سیستم)")
    except Exception:
        pass

    items.sort(key=lambda x: (0 if "توصیه" in x[1] else (2 if "VPN" in x[1] else 1)))
    if not items:
        items.append(("127.0.0.1", "(لوکال)"))
    return items

@app.get("/manifest.json")
def get_manifest():
    manifest = {
        "name": "Gold Analyzer",
        "short_name": "GoldAnalyzer",
        "description": "سیستم هوشمند تحلیل و اسکلپ طلا (XAU/USD)",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0B0D13",
        "theme_color": "#0B0D13",
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='20' fill='%23121520'/%3E%3Cpath d='M50 15 L78 35 L68 80 L32 80 L22 35 Z' fill='none' stroke='%23FFD700' stroke-width='4'/%3E%3Ctext x='50' y='60' font-size='26' font-family='sans-serif' font-weight='bold' fill='%23FFD700' text-anchor='middle'%3EXAU%3C/text%3E%3C/svg%3E",
                "sizes": "192x192 512x512",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            }
        ]
    }
    return JSONResponse(manifest, media_type="application/manifest+json")

@app.get("/sw.js")
def get_sw():
    js = """
    self.addEventListener('install', (e) => {
        self.skipWaiting();
    });
    self.addEventListener('activate', (e) => {
        return self.clients.claim();
    });
    self.addEventListener('fetch', (e) => {
        // Network first
        e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    });
    """
    return Response(content=js, media_type="application/javascript")

@app.get("/api/status")
def get_status():
    """ارسال داده‌های زنده و تحلیل‌ها به صورت JSON به فرانت‌موبایل"""
    snap = _STATE.get("snapshot") or {}
    sig = _STATE.get("signal") or {}
    sess = _STATE.get("session") or {}
    
    current_p = _STATE.get("last_price")
    if not current_p and (snap.get("current") or {}).get("price"):
        current_p = snap["current"]["price"]

    weekly_rep = get_weekly_report()
    
    ta = sig.get("ta_report", {})
    ict = sig.get("ict_report", {})
    lv = ta.get("latest_values", {})
    mtf = ta.get("mtf_trend", {})
    sess_obj = sess.get("current_session", {})

    status_data = {
        "price": current_p,
        "last_updated": _STATE.get("last_updated"),
        "session": {
            "name": sess_obj.get("name", "—"),
            "timing_advice": sess.get("timing", {}).get("advice", ""),
            "market_open": sess.get("market_status", {}).get("can_trade", True),
            "market_badge": sess.get("market_status", {}).get("badge_text", "🟢 بازار باز است"),
        },
        "signal": {
            "direction": sig.get("signal", "WAIT"),
            "grade": sig.get("grade", "D"),
            "confidence": sig.get("confidence", 0),
            "label": sig.get("label", "در حال پردازش"),
            "entry": sig.get("entry"),
            "sl": sig.get("sl"),
            "tp1": sig.get("tp1"),
            "tp2": sig.get("tp2"),
            "tp3": sig.get("tp3"),
            "rr1": sig.get("rr1", 0),
            "risk_pips": sig.get("risk_pips", 0),
            "net_score": sig.get("net_score", 0),
            "reasons": sig.get("reasoning", []),
            "warnings": sig.get("warnings", []),
        },
        "ict": {
            "zone": ict.get("premium_discount", {}).get("zone", "equilibrium"),
            "current_pct": round(ict.get("premium_discount", {}).get("current_pct", 0.5) * 100, 1),
            "range_high": ict.get("premium_discount", {}).get("range_high"),
            "range_low": ict.get("premium_discount", {}).get("range_low"),
            "in_kill_zone": ict.get("kill_zone", {}).get("in_kill_zone", False),
            "kill_zone_name": ict.get("kill_zone", {}).get("kill_zone_name", "None"),
            "signals": ict.get("signals", []),
            "confirmation_count": ict.get("confirmation_count", 0),
            "dol": ict.get("draw_on_liquidity", {}),
            "inst_levels": ict.get("institutional_levels", {}),
            "adr": ict.get("adr_metrics", {}),
            "model_2022": ict.get("model_2022", {}),
        },
        "technical": {
            "rsi": lv.get("RSI"),
            "macd_hist": lv.get("MACD_Hist"),
            "ema200": lv.get("EMA_200"),
            "daily_trend": mtf.get("daily", {}).get("direction", "—"),
            "h4_trend": mtf.get("h4", {}).get("direction", "—"),
            "h1_trend": mtf.get("h1", {}).get("direction", "—"),
            "m15_trend": mtf.get("m15", {}).get("direction", "—"),
            "overall_trend": mtf.get("overall", "—"),
        },
        "weekly": {
            "title": weekly_rep.get("title", ""),
            "date_range": weekly_rep.get("date_range", ""),
            "total": weekly_rep.get("total_signals", 0),
            "win_rate": weekly_rep.get("win_rate", 0),
            "target_hit_summary": weekly_rep.get("target_hit_summary", ""),
            "tp_hit_count": weekly_rep.get("tp_hit_count", 0),
            "sl_hit_count": weekly_rep.get("sl_hit_count", 0),
            "be_count": weekly_rep.get("be_count", 0),
            "signals": weekly_rep.get("signals", [])[:20]  # آخرین ۲۰ سیگنال
        }
    }
    cleaned = sanitize_for_json(status_data)
    return Response(content=json.dumps(cleaned, ensure_ascii=False), media_type="application/json")

@app.post("/api/refresh")
def force_refresh():
    """درخواست به‌روزرسانی فوری بازار از موبایل"""
    try:
        snap = get_full_market_snapshot()
        utc_now = datetime.now(pytz.UTC)
        sig = generate_signal(snap, utc_time=utc_now)
        sess = full_session_report(snap, utc_now)
        price = (snap.get("current") or {}).get("price")
        
        _STATE["snapshot"] = snap
        _STATE["signal"] = sig
        _STATE["session"] = sess
        _STATE["last_price"] = price
        _STATE["last_updated"] = datetime.now().strftime("%H:%M:%S")
        res_payload = {"status": "ok", "time": _STATE["last_updated"]}
        return Response(content=json.dumps(res_payload, ensure_ascii=False), media_type="application/json")
    except Exception as e:
        err_payload = {"status": "error", "message": str(e)}
        return Response(content=json.dumps(err_payload, ensure_ascii=False), media_type="application/json", status_code=500)

@app.get("/", response_class=HTMLResponse)
def index_html():
    _template_path = os.path.join(_DIR, "ui_template.html")
    with open(_template_path, "r", encoding="utf-8") as f:
        return f.read()


def print_banner(ips, port):
    print("=" * 68)
    print("      ⚜  GOLD ANALYZER — سرور موبایل هوشمند طلا (PWA)  ⚜ ")
    print("=" * 68)
    print(" سرور با موفقیت راه‌اندازی شد و آماده اتصال گوشی است.\n")
    print(" 📱 برای باز کردن برنامه روی گوشی:")
    print("    1. اطمینان حاصل کنید گوشی به همین شبکه Wi-Fi متصل است.")
    print("    2. آدرس زیر را در مرورگر کروم گوشی باز کنید:\n")
    for ip, label in ips:
        print(f"       👉  http://{ip}:{port}   {label}")
    print("\n 💡 نحوه نصب روی گوشی (مانند فایل APK بومی):")
    print("    - پس از باز شدن صفحه، روی دکمه طلایی 'نصب اپلیکیشن' بزنید.")
    print("    - یا در منوی کروم (سه نقطه بالا) گزینه 'Add to Home screen' را انتخاب کنید.")
    print("    - آیکون Gold Analyzer روی صفحه موبایل اضافه می‌شود و تمام‌صفحه اجرا خواهد شد.")
    print("=" * 68)
    print(" برای توقف سرور کلیدهای Ctrl + C را در این پنجره فشار دهید.\n")

if __name__ == "__main__":
    port = 8080
    ips = get_network_ips()
    print_banner(ips, port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
