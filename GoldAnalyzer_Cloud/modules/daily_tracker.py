"""
ماژول ردیاب اسکلپ روزانه طلا (Daily Scalp Tracker)
------------------------------------------------
محدود کردن سیگنال‌ها به حداکثر ۲ تا ۳ پوزیشن باکیفیت در روز
جلوگیری از Over-trading و اسپم سیگنال با سیستم Cooldown
"""

import os
import json
from datetime import datetime, timezone
import pytz

# مسیر ذخیره وضعیت روزانه
_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BRIDGE_DIR = os.path.join(_DIR, "bridge")
_STATE_FILE = os.path.join(_BRIDGE_DIR, "daily_scalp_state.json")

MAX_DAILY_SCALPS = 3       # حداکثر ۳ معامله اسکلپ در روز
COOLDOWN_MINUTES = 45      # حداقل فاصله زمانی بین دو سیگنال (دقیقه)


def _ensure_dir():
    os.makedirs(_BRIDGE_DIR, exist_ok=True)


def _load_state() -> dict:
    _ensure_dir()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    default_state = {
        "date": today_str,
        "count": 0,
        "max_daily": MAX_DAILY_SCALPS,
        "last_signal_time": None,
        "signals": []
    }

    if not os.path.exists(_STATE_FILE):
        return default_state

    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # اگر تاریخ روز عوض شده بود، ریست به روز جدید
        if data.get("date") != today_str:
            default_state["date"] = today_str
            _save_state(default_state)
            return default_state
        return data
    except Exception:
        return default_state


def _save_state(state: dict):
    _ensure_dir()
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[DailyTracker] Error saving state: {e}")


def get_daily_status() -> dict:
    """دریافت وضعیت سهمیه اسکلپ امروز"""
    state = _load_state()
    today_count = state.get("count", 0)
    max_daily   = state.get("max_daily", MAX_DAILY_SCALPS)
    remaining   = max(0, max_daily - today_count)
    last_time_str = state.get("last_signal_time")

    in_cooldown = False
    cooldown_rem_min = 0

    if last_time_str:
        try:
            last_dt = datetime.fromisoformat(last_time_str)
            now_dt  = datetime.now(timezone.utc)
            diff_sec = (now_dt - last_dt).total_seconds()
            cooldown_sec = COOLDOWN_MINUTES * 60
            if diff_sec < cooldown_sec:
                in_cooldown = True
                cooldown_rem_min = int((cooldown_sec - diff_sec) / 60) + 1
        except Exception:
            pass

    return {
        "date":              state.get("date"),
        "count":             today_count,
        "max_daily":         max_daily,
        "remaining":         remaining,
        "is_limit_reached":  today_count >= max_daily,
        "in_cooldown":       in_cooldown,
        "cooldown_rem_min":  cooldown_rem_min,
        "signals":           state.get("signals", []),
    }


def can_issue_scalp_signal() -> tuple[bool, str]:
    """
    بررسی اینکه آیا اجازه صدور سیگنال اسکلپ جدید در امروز وجود دارد یا خیر.
    خروجی: (مجاز بودن: bool, دلیل: str)
    """
    status = get_daily_status()

    if status["is_limit_reached"]:
        return False, f"⛔ سقف معاملات اسکلپ روزانه تکمیل شد ({status['count']} از {status['max_daily']} پوزیشن). برای حفظ سرمایه، معاملات امروز به پایان رسید."

    if status["in_cooldown"]:
        return False, f"⏳ فاصله استراحت بین سیگنال‌ها (Cooldown): {status['cooldown_rem_min']} دقیقه تا امکان صدور سیگنال بعدی باقی مانده است."

    return True, f"✅ مجاز به معامله (پوزیشن {status['count'] + 1} از {status['max_daily']} امروز)"


def record_new_signal(signal_data: dict) -> dict:
    """ثبت سیگنال جدید در سوابق امروز و آپدیت شمارنده روزانه"""
    state = _load_state()
    state["count"] = state.get("count", 0) + 1
    now_iso = datetime.now(timezone.utc).isoformat()
    state["last_signal_time"] = now_iso

    summary = {
        "id": f"SCALP-{state['count']}-{datetime.now().strftime('%H%M%S')}",
        "time": datetime.now().strftime("%H:%M:%S"),
        "direction": signal_data.get("signal"),
        "grade": signal_data.get("grade"),
        "entry": signal_data.get("entry"),
        "sl": signal_data.get("sl"),
        "tp1": signal_data.get("tp1"),
        "tp2": signal_data.get("tp2"),
        "tp3": signal_data.get("tp3"),
        "timestamp": now_iso
    }
    state["signals"].append(summary)
    _save_state(state)
    return summary
