"""
ماژول بایگانی و ردیابی هفتگی سیگنال‌های طلا (Weekly Signal Tracker & Archive)
--------------------------------------------------------------------------
- ذخیره‌سازی نامحدود تمام سیگنال‌ها و فرصت‌های معاملاتی در طول یک هفته معاملاتی
- ریست و بایگانی خودکار در پایان هر هفته معاملاتی (جمعه شب / یکشنبه شب)
- ردیابی سود و زیان (TP1, TP2, TP3, SL) به صورت پویا با قیمت لحظه‌ای
- ارائه خروجی CSV و گزارش آماری جامع هفتگی
"""

import os
import json
import csv
from datetime import datetime, timezone, timedelta
import pytz

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BRIDGE_DIR = os.path.join(_DIR, "bridge")
_ARCHIVE_DIR = os.path.join(_BRIDGE_DIR, "weekly_archive")
_WEEKLY_FILE = os.path.join(_BRIDGE_DIR, "weekly_signals.json")
_WEEKLY_CSV_FILE = os.path.join(_BRIDGE_DIR, "weekly_signals.csv")


def _ensure_dirs():
    os.makedirs(_BRIDGE_DIR, exist_ok=True)
    os.makedirs(_ARCHIVE_DIR, exist_ok=True)


def get_trading_week_info(dt: datetime = None) -> dict:
    """
    محاسبه شناسه و مشخصات هفته معاملاتی طلا (XAU/USD).
    هفته معاملاتی طلا از یکشنبه ساعت ۲۲:۰۰ UTC شروع و جمعه ساعت ۲۱:۰۰ UTC خاتمه می‌یابد.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # اگر یکشنبه بعد از ۲۲:۰۰ باشد، متعلق به هفته جدید است
    calc_dt = dt
    if dt.weekday() == 6 and dt.hour >= 22:
        calc_dt = dt + timedelta(days=1)

    iso_year, iso_week, _ = calc_dt.isocalendar()
    week_id = f"{iso_year}-W{iso_week:02d}"

    # محاسبه تاریخ شروع (دوشنبه این هفته) و پایان (جمعه این هفته)
    # شروع هفته بر اساس دوشنبه استاندارد ISO
    monday = calc_dt - timedelta(days=calc_dt.weekday())
    friday = monday + timedelta(days=4)

    start_str = monday.strftime("%Y/%m/%d")
    end_str = friday.strftime("%Y/%m/%d")
    date_range = f"{start_str} الی {end_str}"

    return {
        "week_id": week_id,
        "iso_year": iso_year,
        "iso_week": iso_week,
        "title": f"هفته معاملاتی {iso_week} ({iso_year})",
        "date_range": date_range,
        "monday_date": start_str,
        "friday_date": end_str
    }


def _load_weekly_state() -> dict:
    """بارگذاری وضعیت سیگنال‌های هفتگی، با چک کردن تغییر هفته و بایگانی خودکار"""
    _ensure_dirs()
    current_week = get_trading_week_info()
    cur_week_id = current_week["week_id"]

    default_state = {
        "week_id": cur_week_id,
        "title": current_week["title"],
        "date_range": current_week["date_range"],
        "count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "signals": []
    }

    if not os.path.exists(_WEEKLY_FILE):
        _save_weekly_state(default_state)
        return default_state

    try:
        with open(_WEEKLY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        saved_week_id = data.get("week_id")
        # اگر هفته معاملاتی تغییر کرده، هفته قبلی را بایگانی و فایل هفتگی را ریست کن
        if saved_week_id and saved_week_id != cur_week_id:
            # بایگانی هفته قبل
            archive_path = os.path.join(_ARCHIVE_DIR, f"signals_{saved_week_id}.json")
            try:
                with open(archive_path, "w", encoding="utf-8") as af:
                    json.dump(data, af, ensure_ascii=False, indent=2)
                print(f"[WeeklyTracker] Archived previous week {saved_week_id} to {archive_path}")
            except Exception as e:
                print(f"[WeeklyTracker] Error archiving week {saved_week_id}: {e}")

            # ریست برای هفته جدید
            _save_weekly_state(default_state)
            return default_state

        return data
    except Exception as e:
        print(f"[WeeklyTracker] Error loading weekly state: {e}")
        return default_state


def _save_weekly_state(state: dict):
    _ensure_dirs()
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(_WEEKLY_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WeeklyTracker] Error saving weekly state: {e}")


def record_weekly_signal(signal_data: dict, utc_time: datetime = None) -> dict:
    """
    ثبت یک سیگنال با اطلاعات کامل در بایگانی هفتگی.
    سیگنال‌های با کیفیت پایین (Grade C و D) و سیگنال‌های اسپم/تکراری فیلتر می‌شوند.
    """
    if not signal_data or signal_data.get("signal") not in ("BUY", "SELL"):
        return None

    # فیلتر کیفیت سیگنال: فقط گریدهای معتبر A و B با اطمینان بالای ۶۰٪ مجاز به ثبت هستند
    grade = signal_data.get("grade", "D")
    confidence = int(signal_data.get("confidence") or 0)
    if grade in ("C", "D") or confidence < 60:
        return None

    state = _load_weekly_state()
    signals = state.get("signals", [])

    entry = float(signal_data.get("entry") or 0.0)
    direction = signal_data.get("signal")

    if utc_time is None:
        utc_time = datetime.now(timezone.utc)
    elif utc_time.tzinfo is None:
        utc_time = utc_time.replace(tzinfo=timezone.utc)

    # بررسی ثبت تکراری و جلوگیری از اسپم پوزیشن‌های همپوشان
    if signals:
        last_sig = signals[-1]
        same_dir = last_sig.get("direction") == direction
        price_diff = abs(float(last_sig.get("entry", 0.0)) - entry)
        if same_dir and price_diff < 1.8:
            return last_sig

        active_same_dir = [s for s in signals if s.get("direction") == direction and s.get("status") == "ACTIVE"]
        if active_same_dir:
            last_active = active_same_dir[-1]
            act_diff = abs(float(last_active.get("entry", 0.0)) - entry)
            if act_diff < 1.8:
                return last_active

    # زمان محلی تهران برای نمایش خوانا
    tehran_tz = pytz.timezone("Asia/Tehran")
    local_time = utc_time.astimezone(tehran_tz)

    state["count"] = state.get("count", 0) + 1
    sig_num = state["count"]
    iso_week = state.get("week_id", "").split("-W")[-1] if "-W" in state.get("week_id", "") else "01"
    sig_id = f"XAU-W{iso_week}-{sig_num:03d}"

    sl = float(signal_data.get("sl") or 0.0)
    tp1 = float(signal_data.get("tp1") or 0.0)
    tp2 = float(signal_data.get("tp2") or 0.0)
    tp3 = float(signal_data.get("tp3") or 0.0)

    risk_dollars = round(abs(entry - sl), 2) if (entry and sl) else 0.0
    risk_pips = int(risk_dollars * 10)

    # استخراج نام سشن معاملاتی
    sess_obj = signal_data.get("session_report", {}).get("current_session", {})
    sess_name = sess_obj.get("name", "—")

    record = {
        "id": sig_id,
        "week_id": state.get("week_id"),
        "number": sig_num,
        "timestamp_utc": utc_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "timestamp_local": local_time.strftime("%Y/%m/%d - %H:%M"),
        "time_only": local_time.strftime("%H:%M"),
        "date_only": local_time.strftime("%m/%d"),
        "direction": direction,
        "grade": grade,
        "confidence": confidence,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk_dollars": risk_dollars,
        "risk_pips": risk_pips,
        "rr1": signal_data.get("rr1", 1.4),
        "rr2": signal_data.get("rr2", 2.3),
        "rr3": signal_data.get("rr3", 3.6),
        "net_score": round(float(signal_data.get("net_score") or 0.0), 1),
        "session": sess_name,
        "status": "ACTIVE",  # ACTIVE, TP1_HIT, TP2_HIT, TP3_HIT, BREAKEVEN, SL_HIT
        "status_fa": "⚡ فعال (در جریان)",
        "reasons": signal_data.get("reasoning", []),
        "warnings": signal_data.get("warnings", []),
        "ict_summary": signal_data.get("ict_summary", {}),
    }

    signals.append(record)
    state["signals"] = signals
    _save_weekly_state(state)

    # ثبت در CSV هفتگی
    _append_to_csv(record)

    print(f"[WeeklyTracker] Registered new high-conviction signal: {record['id']} ({direction} @ {entry}, Grade: {grade})")
    return record


def update_weekly_signal_statuses(current_price: float, high_price: float = None, low_price: float = None) -> list:
    """
    به‌روزرسانی وضعیت سیگنال‌های هفتگی با سیستم پیشرفته مدیریت سود (Breakeven) و تارگت‌ها.
    پس از اصابت تارگت ۱، حد ضرر معامله به نقطه ورود (ریسک‌فری) منتقل شده و معامله دیگر نمی‌تواند استاپ بخورد.
    """
    if not current_price or current_price <= 0:
        return []

    h_price = high_price if high_price and high_price > 0 else current_price
    l_price = low_price if low_price and low_price > 0 else current_price

    state = _load_weekly_state()
    signals = state.get("signals", [])
    changed = False

    for s in signals:
        st = s.get("status")
        if st in ("TP3_HIT", "SL_HIT", "BREAKEVEN"):
            continue  # معامله نهایی شده است

        d = s.get("direction")
        entry = float(s.get("entry", 0))
        sl = float(s.get("sl", 0))
        tp1 = float(s.get("tp1", 0))
        tp2 = float(s.get("tp2", 0))
        tp3 = float(s.get("tp3", 0))

        if d == "BUY":
            # اگر معامله قبلاً به TP1 یا TP2 رسیده باشد: حد ضرر به نقطه ورود منتقل شده
            if st in ("TP1_HIT", "TP2_HIT"):
                if tp3 and h_price >= tp3:
                    s["status"] = "TP3_HIT"
                    s["status_fa"] = "🎯🎯🎯 تارگت ۳ (سود کامل)"
                    changed = True
                elif tp2 and h_price >= tp2 and st != "TP2_HIT":
                    s["status"] = "TP2_HIT"
                    s["status_fa"] = "🎯🎯 تارگت ۲ (سود عالی)"
                    changed = True
                elif l_price <= entry:
                    s["status"] = "BREAKEVEN"
                    s["status_fa"] = "🛡️ خروج ریسک‌فری (سود ذخیره شد)"
                    changed = True
            else:
                # معامله ACTIVE اولیه
                if sl and l_price <= sl:
                    s["status"] = "SL_HIT"
                    s["status_fa"] = "❌ حد ضرر (SL)"
                    changed = True
                elif tp3 and h_price >= tp3:
                    s["status"] = "TP3_HIT"
                    s["status_fa"] = "🎯🎯🎯 تارگت ۳ (سود کامل)"
                    changed = True
                elif tp2 and h_price >= tp2:
                    s["status"] = "TP2_HIT"
                    s["status_fa"] = "🎯🎯 تارگت ۲ (سود عالی)"
                    changed = True
                elif tp1 and h_price >= tp1:
                    s["status"] = "TP1_HIT"
                    s["status_fa"] = "🎯 تارگت ۱ (سود اولیه - ریسک‌فری)"
                    changed = True

        elif d == "SELL":
            # اگر معامله قبلاً به TP1 یا TP2 رسیده باشد: حد ضرر به نقطه ورود منتقل شده
            if st in ("TP1_HIT", "TP2_HIT"):
                if tp3 and l_price <= tp3:
                    s["status"] = "TP3_HIT"
                    s["status_fa"] = "🎯🎯🎯 تارگت ۳ (سود کامل)"
                    changed = True
                elif tp2 and l_price <= tp2 and st != "TP2_HIT":
                    s["status"] = "TP2_HIT"
                    s["status_fa"] = "🎯🎯 تارگت ۲ (سود عالی)"
                    changed = True
                elif h_price >= entry:
                    s["status"] = "BREAKEVEN"
                    s["status_fa"] = "🛡️ خروج ریسک‌فری (سود ذخیره شد)"
                    changed = True
            else:
                # معامله ACTIVE اولیه
                if sl and h_price >= sl:
                    s["status"] = "SL_HIT"
                    s["status_fa"] = "❌ حد ضرر (SL)"
                    changed = True
                elif tp3 and l_price <= tp3:
                    s["status"] = "TP3_HIT"
                    s["status_fa"] = "🎯🎯🎯 تارگت ۳ (سود کامل)"
                    changed = True
                elif tp2 and l_price <= tp2:
                    s["status"] = "TP2_HIT"
                    s["status_fa"] = "🎯🎯 تارگت ۲ (سود عالی)"
                    changed = True
                elif tp1 and l_price <= tp1:
                    s["status"] = "TP1_HIT"
                    s["status_fa"] = "🎯 تارگت ۱ (سود اولیه - ریسک‌فری)"
                    changed = True

    if changed:
        _save_weekly_state(state)

    return signals


def get_weekly_report() -> dict:
    """
    دریافت گزارش جامع و آماری تمام سیگنال‌های هفته جاری با محاسبه دقیق وین‌ریت و تارگت‌ها
    """
    state = _load_weekly_state()
    signals = state.get("signals", [])

    total = len(signals)
    buy_count = sum(1 for s in signals if s.get("direction") == "BUY")
    sell_count = sum(1 for s in signals if s.get("direction") == "SELL")

    active_count = sum(1 for s in signals if s.get("status") == "ACTIVE")
    tp1_count = sum(1 for s in signals if s.get("status") == "TP1_HIT")
    tp2_count = sum(1 for s in signals if s.get("status") == "TP2_HIT")
    tp3_count = sum(1 for s in signals if s.get("status") == "TP3_HIT")
    be_count  = sum(1 for s in signals if s.get("status") == "BREAKEVEN")
    tp_hit_count = tp1_count + tp2_count + tp3_count + be_count
    sl_hit_count = sum(1 for s in signals if s.get("status") == "SL_HIT")

    closed_count = tp_hit_count + sl_hit_count

    # نرخ موفقیت (Win Rate): نسبت معاملات سودده و ریسک‌فری به کل معاملات بسته شده
    if closed_count > 0:
        win_rate = round((tp_hit_count / closed_count) * 100, 1)
    else:
        win_rate = 0.0

    # درصد تارگت‌های خورده شده به کل سیگنال‌ها (حتی معاملات در جریان)
    target_hit_pct = round((tp_hit_count / total) * 100, 1) if total > 0 else 0.0

    avg_rr = 0.0
    avg_conf = 0.0
    if total > 0:
        avg_rr = round(sum(float(s.get("rr1", 1.4)) for s in signals) / total, 2)
        avg_conf = round(sum(int(s.get("confidence", 70)) for s in signals) / total, 1)

    return {
        "week_id":            state.get("week_id"),
        "title":              state.get("title"),
        "date_range":         state.get("date_range"),
        "last_updated":       state.get("last_updated"),
        "total_signals":      total,
        "buy_count":          buy_count,
        "sell_count":         sell_count,
        "active_count":       active_count,
        "tp1_count":          tp1_count,
        "tp2_count":          tp2_count,
        "tp3_count":          tp3_count,
        "be_count":           be_count,
        "tp_hit_count":       tp_hit_count,
        "sl_hit_count":       sl_hit_count,
        "closed_count":       closed_count,
        "win_rate":           win_rate,
        "target_hit_pct":     target_hit_pct,
        "target_hit_summary": f"{tp_hit_count} از {total} پوزیشن",
        "avg_rr":             avg_rr,
        "avg_confidence":     avg_conf,
        "signals":            list(reversed(signals))  # جدیدترین‌ها در ابتدا
    }


def reset_weekly_signals_manual() -> bool:
    """
    بازنشانی دستی سیگنال‌های هفته (بایگانی هفته فعلی و شروع تازه)
    """
    _ensure_dirs()
    state = _load_weekly_state()
    saved_week_id = state.get("week_id", "current")

    archive_path = os.path.join(_ARCHIVE_DIR, f"signals_manual_reset_{saved_week_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    try:
        with open(archive_path, "w", encoding="utf-8") as af:
            json.dump(state, af, ensure_ascii=False, indent=2)
    except Exception:
        pass

    current_week = get_trading_week_info()
    new_state = {
        "week_id": current_week["week_id"],
        "title": current_week["title"],
        "date_range": current_week["date_range"],
        "count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "signals": []
    }
    _save_weekly_state(new_state)

    # پاک کردن CSV فعلی
    try:
        if os.path.exists(_WEEKLY_CSV_FILE):
            os.remove(_WEEKLY_CSV_FILE)
    except Exception:
        pass

    return True


def _append_to_csv(record: dict):
    """ثبت در فایل اکسل/CSV هفتگی"""
    _ensure_dirs()
    file_exists = os.path.exists(_WEEKLY_CSV_FILE)
    try:
        with open(_WEEKLY_CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "شناسه", "تاریخ و زمان", "جهت", "قیمت ورود",
                    "حد ضرر (SL)", "هدف ۱ (TP1)", "هدف ۲ (TP2)", "هدف ۳ (TP3)",
                    "ریسک دلاری", "ریسک (پیپ)", "نسبت R:R", "گرید",
                    "اطمینان", "سشن معاملاتی", "وضعیت"
                ])
            writer.writerow([
                record["id"],
                record["timestamp_local"],
                record["direction"],
                f"${record['entry']:,.2f}",
                f"${record['sl']:,.2f}",
                f"${record['tp1']:,.2f}",
                f"${record['tp2']:,.2f}",
                f"${record['tp3']:,.2f}",
                f"${record['risk_dollars']:.2f}",
                record["risk_pips"],
                f"1:{record['rr1']}",
                record["grade"],
                f"{record['confidence']}%",
                record["session"],
                record["status_fa"]
            ])
    except Exception as e:
        print(f"[WeeklyTracker] Error appending to CSV: {e}")
