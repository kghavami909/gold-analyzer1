"""
Session Analyzer Module
------------------------
Identifies current trading session (Asia / London / New York / Overlap)
and analyzes session-specific price behavior for XAU/USD.

Session times (UTC):
  Asia/Tokyo :  00:00 – 08:00 UTC
  London     :  07:00 – 16:00 UTC  (peak: 07:00-12:00)
  New York   :  13:00 – 22:00 UTC  (peak: 13:00-17:00)
  London/NY  :  13:00 – 16:00 UTC  (highest volatility for gold)
  Dead zone  :  22:00 – 00:00 UTC

Gold tends to move most during London open and London/NY overlap.
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
import pytz


# ─────────────────────────────────────────────
# SESSION DEFINITIONS
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# SESSION DEFINITIONS
# ─────────────────────────────────────────────

SESSIONS = {
    "weekend_closed": {
        "name":    "تعطیلات آخر هفته (بازار بسته)",
        "start":   time(0, 0),
        "end":     time(23, 59),
        "peak_start": time(0, 0),
        "peak_end":   time(0, 0),
        "color":   "red",
        "typical_range_pct": 0.0,
        "note":    "بازار جهانی طلا در روزهای شنبه و یکشنبه کاملاً تعطیل است",
    },
    "daily_break": {
        "name":    "استراحت و تسویه روزانه (Rollover)",
        "start":   time(21, 0),
        "end":     time(22, 0),
        "peak_start": time(21, 0),
        "peak_end":   time(22, 0),
        "color":   "yellow",
        "typical_range_pct": 0.0,
        "note":    "ساعت تسویه حساب روزانه بروکرها و بورس فلزات (۲۱:۰۰ تا ۲۲:۰۰ UTC) — معاملات متوقف است",
    },
    "asia": {
        "name":    "سشن آسیا (توکیو)",
        "start":   time(0, 0),
        "end":     time(8, 0),
        "peak_start": time(0, 0),
        "peak_end":   time(6, 0),
        "color":   "cyan",
        "typical_range_pct": 0.4,   # gold typically moves 0.3-0.6% in Asia
        "note":    "نوسان پایین، اغلب خنثی یا Range-bound. فرصت‌های Fade the Spike",
    },
    "london": {
        "name":    "سشن لندن",
        "start":   time(7, 0),
        "end":     time(16, 0),
        "peak_start": time(7, 0),
        "peak_end":   time(12, 0),
        "color":   "yellow",
        "typical_range_pct": 0.8,
        "note":    "مهم‌ترین سشن برای طلا. اغلب روند روز اینجا شکل می‌گیرد",
    },
    "new_york": {
        "name":    "سشن نیویورک",
        "start":   time(13, 0),
        "end":     time(21, 0),
        "peak_start": time(13, 0),
        "peak_end":   time(17, 0),
        "color":   "green",
        "typical_range_pct": 0.9,
        "note":    "پراهمیت‌ترین اخبار USD در این سشن منتشر می‌شود",
    },
    "overlap": {
        "name":    "اوورلپ لندن/نیویورک",
        "start":   time(13, 0),
        "end":     time(16, 0),
        "peak_start": time(13, 0),
        "peak_end":   time(16, 0),
        "color":   "red",
        "typical_range_pct": 1.2,
        "note":    "بیشترین نقدینگی و نوسان طلا. بهترین زمان برای معامله",
    },
    "dead_zone": {
        "name":    "ساعات کم‌نوسان (Dead Zone)",
        "start":   time(22, 0),
        "end":     time(0, 0),
        "peak_start": time(22, 0),
        "peak_end":   time(0, 0),
        "color":   "grey",
        "typical_range_pct": 0.2,
        "note":    "ساعات پایانی شب بازار جهانی — نقدینگی پایین، ریسک اسپایک بالا",
    }
}


# ─────────────────────────────────────────────
# MARKET OPEN / CLOSED DETECTION
# ─────────────────────────────────────────────

def check_market_status(utc_time: datetime = None) -> dict:
    """
    تشخیص دقیق باز یا بسته بودن بازار جهانی طلا (XAU/USD).
    
    قوانین باز و بسته بودن بازار طلا:
      ۱. روزهای شنبه و یکشنبه:
         - بازار جمعه شب ساعت ۲۱:۰۰ UTC بسته می‌شود.
         - شنبه: بازار در سراسر جهان کاملاً بسته است.
         - یکشنبه: بازار تا ساعت ۲۲:۰۰ UTC تعطیل است و سپس با سشن سیدنی بازگشایی می‌شود.
      ۲. ساعت تسویه و استراحت روزانه (Daily Rollover):
         - دوشنبه تا پنج‌شنبه بین ساعت ۲۱:۰۰ تا ۲۲:۰۰ UTC (ساعت ۱۷:۰۰ تا ۱۸:۰۰ نیویورک).
         - در این یک ساعت معاملات متوقف، تسویه انجام شده و اسپردها به شدت باز می‌شوند.
      ۳. ساعات کم‌نقدینگی (Dead Zone):
         - ۲۲:۰۰ تا ۰۰:۰۰ UTC (قبل از ورود معامله‌گران توکیو).
    """
    if utc_time is None:
        utc_time = datetime.now(pytz.UTC)

    weekday = utc_time.weekday()  # Monday is 0, Sunday is 6
    hour = utc_time.hour
    minute = utc_time.minute

    # ۱. بررسی روز جمعه بعد از ساعت 21:00 UTC (بسته شدن هفتگی بازار)
    if weekday == 4 and hour >= 21:
        return {
            "is_open": False,
            "status": "weekend_closed",
            "name": "تعطیلات آخر هفته",
            "badge_text": "🔴 بازار بسته است (پایان هفته)",
            "reason": "بازار جهانی طلا در پایان روز جمعه (ساعت ۲۱:۰۰ UTC) بسته شد و تا یکشنبه شب تعطیل است.",
            "can_trade": False,
            "color": "#F6465D"
        }

    # ۲. شنبه (کامل تعطیل)
    if weekday == 5:
        return {
            "is_open": False,
            "status": "weekend_closed",
            "name": "تعطیلات آخر هفته (شنبه)",
            "badge_text": "🔴 بازار بسته است (شنبه)",
            "reason": "امروز شنبه است و تمامی بازارهای بین‌المللی طلا و فارکس در سراسر جهان تعطیل هستند.",
            "can_trade": False,
            "color": "#F6465D"
        }

    # ۳. یکشنبه (تا قبل از ساعت 22:00 UTC بسته است)
    if weekday == 6:
        if hour < 22:
            rem_h = 21 - hour
            rem_m = 60 - minute
            return {
                "is_open": False,
                "status": "weekend_closed",
                "name": "تعطیلات آخر هفته (یکشنبه)",
                "badge_text": "🔴 بازار بسته است (یکشنبه)",
                "reason": f"امروز یکشنبه است. بازار جهانی طلا ساعت ۲۲:۰۰ UTC (حدود {rem_h} ساعت دیگر) بازگشایی خواهد شد.",
                "can_trade": False,
                "color": "#F6465D"
            }
        else:
            return {
                "is_open": True,
                "status": "pre_market",
                "name": "پیش‌گشایش هفته (سیدنی)",
                "badge_text": "🟡 پیش‌گشایش بازار (اسپرد بالا)",
                "reason": "بازار هفته جدید به تازگی بازگشایی شده است. تا باز شدن توکیو اسپردها بالاست.",
                "can_trade": False,
                "color": "#F0B90B"
            }

    # ۴. استراحت و تسویه روزانه دوشنبه تا پنج‌شنبه (21:00 تا 22:00 UTC)
    if 0 <= weekday <= 3 and hour == 21:
        rem_m = 60 - minute
        return {
            "is_open": False,
            "status": "daily_break",
            "name": "استراحت و تسویه روزانه (Rollover)",
            "badge_text": "⏸ استراحت روزانه (تسویه ۲۱-۲۲ UTC)",
            "reason": f"ساعت تسویه روزانه بازار و بروکرها (Daily Rollover). معاملات متوقف است ({rem_m} دقیقه تا پایان).",
            "can_trade": False,
            "color": "#F0B90B"
        }

    # ۵. ساعات کم‌نوسان شبانه (22:00 تا 00:00 UTC)
    if hour >= 22:
        return {
            "is_open": True,
            "status": "dead_zone",
            "name": "ساعات کم‌نقدینگی (Dead Zone)",
            "badge_text": "⚠️ ساعات کم‌نقدینگی",
            "reason": "فاصله بین پایان نیویورک و شروع آسیا. نقدینگی پایین و نامناسب برای اسکلپ.",
            "can_trade": False,
            "color": "#94A3B8"
        }

    # ۶. بازار باز، فعال و مناسب معامله است
    return {
        "is_open": True,
        "status": "open",
        "name": "بازار فعال و باز",
        "badge_text": "🟢 بازار فعال و باز است",
        "reason": "بازار جهانی طلا باز است و شرایط معاملاتی فعال می‌باشد.",
        "can_trade": True,
        "color": "#0ECB81"
    }


# ─────────────────────────────────────────────
# CURRENT SESSION DETECTION
# ─────────────────────────────────────────────

def get_current_session(utc_time: datetime = None) -> dict:
    """
    تشخیص سشن فعال با در نظر گرفتن تعطیلات پایان هفته و استراحت روزانه.
    """
    if utc_time is None:
        utc_time = datetime.now(pytz.UTC)

    market_st = check_market_status(utc_time)

    # اگر بازار در تعطیلات آخر هفته یا استراحت روزانه باشد:
    if market_st["status"] in ("weekend_closed", "daily_break"):
        session = SESSIONS[market_st["status"]].copy()
        session["key"] = market_st["status"]
        session["utc_now"] = utc_time.strftime("%H:%M UTC")
        session["is_peak"] = False
        session["minutes_remaining"] = 0
        session["next_session"] = "asia"
        session["market_status"] = market_st
        return session

    current = utc_time.time().replace(second=0, microsecond=0)

    # تشخیص سشن‌های عادی معاملاتی
    if time(13, 0) <= current < time(16, 0):
        active = "overlap"
    elif time(16, 0) <= current < time(21, 0):
        active = "new_york"
    elif time(7, 0) <= current < time(13, 0):
        active = "london"
    elif time(0, 0) <= current < time(7, 0):
        active = "asia"
    else:
        active = "dead_zone"  # 22:00–00:00 UTC

    session = SESSIONS[active].copy()
    session["key"]         = active
    session["utc_now"]     = utc_time.strftime("%H:%M UTC")
    session["market_status"] = market_st

    # Is it peak hours within the session?
    ps = session["peak_start"]
    pe = session["peak_end"]
    if pe > ps:
        session["is_peak"] = ps <= current < pe
    else:
        session["is_peak"] = current >= ps or current < pe

    # Minutes until session ends
    end_dt = utc_time.replace(hour=session["end"].hour, minute=session["end"].minute, second=0)
    if end_dt <= utc_time:
        end_dt = end_dt.replace(day=end_dt.day + 1)
    session["minutes_remaining"] = int((end_dt - utc_time).total_seconds() / 60)

    # Next session
    session_order = ["asia", "london", "overlap", "new_york", "daily_break", "dead_zone"]
    if active in session_order:
        idx = session_order.index(active)
        session["next_session"] = session_order[(idx + 1) % len(session_order)]
    else:
        session["next_session"] = "asia"

    return session



def get_all_sessions_status(utc_time: datetime = None) -> list:
    """Return status of all sessions with open/closed/upcoming state."""
    if utc_time is None:
        utc_time = datetime.now(pytz.UTC)
    current = utc_time.time().replace(second=0, microsecond=0)

    result = []
    for key, sess in SESSIONS.items():
        s, e = sess["start"], sess["end"]
        if e > s:
            is_open = s <= current < e
        else:
            is_open = current >= s or current < e

        result.append({
            "key":      key,
            "name":     sess["name"],
            "open":     is_open,
            "hours":    f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')} UTC",
            "color":    sess["color"],
        })
    return result


# ─────────────────────────────────────────────
# SESSION PRICE ANALYSIS
# ─────────────────────────────────────────────

def analyze_session_ranges(hourly_df: pd.DataFrame, days: int = 10) -> dict:
    """
    Calculate average high-low range for each session over past N days.
    Useful for understanding volatility expectations per session.
    """
    if hourly_df is None or hourly_df.empty:
        return {}

    results = {}
    df = hourly_df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    cutoff = df.index[-1] - pd.Timedelta(days=days)
    df = df[df.index >= cutoff]

    for key, sess in SESSIONS.items():
        if key == "dead_zone":
            continue
        s_h, e_h = sess["start"].hour, sess["end"].hour

        if e_h > s_h:
            mask = (df.index.hour >= s_h) & (df.index.hour < e_h)
        else:
            mask = (df.index.hour >= s_h) | (df.index.hour < e_h)

        session_data = df[mask]
        if session_data.empty:
            results[key] = {"avg_range": 0, "avg_range_pct": 0}
            continue

        # Group by date to get daily session range
        session_data = session_data.copy()
        session_data["date"] = session_data.index.date
        daily_ranges = session_data.groupby("date").apply(
            lambda x: x["High"].max() - x["Low"].min()
        )

        avg_range     = round(float(daily_ranges.mean()), 2)
        avg_close     = round(float(session_data["Close"].mean()), 2)
        avg_range_pct = round((avg_range / avg_close) * 100, 3) if avg_close > 0 else 0

        results[key] = {
            "avg_range":     avg_range,
            "avg_range_pct": avg_range_pct,
            "sample_days":   len(daily_ranges),
        }

    return results


def get_session_high_low(hourly_df: pd.DataFrame, session_key: str) -> dict:
    """
    Get today's high and low for a specific session.
    Used to identify session breakout levels.
    """
    if hourly_df is None or hourly_df.empty:
        return {"high": None, "low": None}

    df = hourly_df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    today = df.index[-1].date()
    sess  = SESSIONS.get(session_key, {})
    if not sess:
        return {"high": None, "low": None}

    s_h = sess["start"].hour
    e_h = sess["end"].hour

    if e_h > s_h:
        mask = (
            (df.index.date == today) &
            (df.index.hour >= s_h) &
            (df.index.hour < e_h)
        )
    else:
        mask = (
            (df.index.date == today) &
            ((df.index.hour >= s_h) | (df.index.hour < e_h))
        )

    session_candles = df[mask]
    if session_candles.empty:
        return {"high": None, "low": None}

    return {
        "high":  round(float(session_candles["High"].max()), 2),
        "low":   round(float(session_candles["Low"].min()), 2),
        "open":  round(float(session_candles["Open"].iloc[0]), 2),
        "close": round(float(session_candles["Close"].iloc[-1]), 2),
        "candles": len(session_candles),
    }


# ─────────────────────────────────────────────
# SESSION-BASED TRADE TIMING
# ─────────────────────────────────────────────

def evaluate_trade_timing(utc_time: datetime = None) -> dict:
    """
    Evaluate whether the current time is good for entering a trade.
    Returns a score and recommendation.
    """
    if utc_time is None:
        utc_time = datetime.now(pytz.UTC)

    session = get_current_session(utc_time)
    key     = session["key"]
    is_peak = session.get("is_peak", False)
    market_st = session.get("market_status") or check_market_status(utc_time)

    if key == "weekend_closed":
        score  = 0
        grade  = "تعطیل"
        advice = f"⛔ {market_st['reason']}"
    elif key == "daily_break":
        score  = 0
        grade  = "استراحت روزانه"
        advice = f"⏸ {market_st['reason']}"
    elif key == "overlap":
        score  = 5
        grade  = "عالی"
        advice = "✅ بهترین زمان معامله — اوورلپ لندن/نیویورک. بیشترین نقدینگی و حرکت قیمت"
    elif key == "london" and is_peak:
        score  = 4
        grade  = "خوب"
        advice = "✅ زمان خوب — اوپن لندن. روندهای مهم روز اینجا شروع می‌شوند"
    elif key == "new_york" and is_peak:
        score  = 4
        grade  = "خوب"
        advice = "✅ زمان خوب — اوپن نیویورک. مراقب اخبار USD باشید"
    elif key == "london":
        score  = 3
        grade  = "متوسط"
        advice = "🔶 سشن لندن (خارج از پیک). معامله ممکن اما نقدینگی کمتر"
    elif key == "new_york":
        score  = 3
        grade  = "متوسط"
        advice = "🔶 سشن نیویورک (خارج از پیک). مراقب بسته‌شدن لندن باشید"
    elif key == "asia":
        score  = 2
        grade  = "ضعیف"
        advice = "🔸 سشن آسیا — نوسان پایین. بهتر است صبر کنید تا لندن باز شود"
    else:
        score  = 1
        grade  = "بسیار ضعیف"
        advice = "⛔ ساعات کم‌نقدینگی — توصیه اکید: بدون معامله"

    # Warn about session transitions (first 15 minutes of session = fake moves)
    if key not in ("weekend_closed", "daily_break"):
        session_start = session["start"]
        minutes_since_open = (utc_time.hour * 60 + utc_time.minute) - \
                             (session_start.hour * 60 + session_start.minute)
        if 0 <= minutes_since_open <= 15:
            advice += "\n⚠️ اوایل باز شدن سشن — احتمال spike و fake move بالاست. صبر کنید"
            score = max(1, score - 1)

    return {
        "session":          session,
        "score":            score,       # 0-5
        "grade":            grade,
        "advice":           advice,
        "is_peak_hours":    is_peak,
        "market_status":    market_st,
        "utc_time":         utc_time.strftime("%Y-%m-%d %H:%M UTC"),
    }


# ─────────────────────────────────────────────
# FULL SESSION REPORT
# ─────────────────────────────────────────────

def full_session_report(snapshot: dict, utc_time: datetime = None) -> dict:
    """
    Generate a complete session analysis report including market open/close status.
    """
    if utc_time is None:
        utc_time = datetime.now(pytz.UTC)

    hourly_df = snapshot.get("gold_1h", pd.DataFrame())

    market_status = check_market_status(utc_time)
    timing        = evaluate_trade_timing(utc_time)
    all_sessions  = get_all_sessions_status(utc_time)
    session_ranges = analyze_session_ranges(hourly_df, days=10)

    # Today's highs/lows per session
    today_levels = {}
    for key in ["asia", "london", "new_york"]:
        today_levels[key] = get_session_high_low(hourly_df, key)

    current_session = timing["session"]

    return {
        "current_session":  current_session,
        "market_status":    market_status,
        "timing":           timing,
        "all_sessions":     all_sessions,
        "session_ranges":   session_ranges,
        "today_levels":     today_levels,
        "utc_time":         utc_time.strftime("%Y-%m-%d %H:%M UTC"),
    }

