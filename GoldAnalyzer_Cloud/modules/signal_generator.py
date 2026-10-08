"""
Signal Generator Module
------------------------
Combines technical + fundamental + session analysis to produce
actionable BUY / SELL / WAIT signals with precise entry, SL, and TP levels.

Signal Logic:
  1. Multi-timeframe confluence (D1 + H4 + H1 + M15 must align)
  2. Minimum score threshold before firing a signal
  3. Entry near key S/R levels
  4. SL based on ATR × multiplier (beyond last swing)
  5. TP at next S/R level (minimum 1:2 R:R ratio)
  6. Session timing filter (no signals in dead zone / Asia)
  7. Calendar filter (no signals 30min before high-impact news)
"""

import pandas as pd
import numpy as np
from datetime import datetime
import pytz

from modules.technical_analysis   import (
    full_technical_report, add_all_indicators, find_key_levels
)
from modules.fundamental_analysis import full_fundamental_report
from modules.session_analyzer      import full_session_report, get_current_session
from modules.daily_tracker         import get_daily_status
from modules.weekly_tracker        import (
    record_weekly_signal, update_weekly_signal_statuses, get_weekly_report
)
from modules.mt5_bridge            import export_signal_to_bridge
from modules.ict_analysis          import full_ict_report, is_kill_zone


# ─────────────────────────────────────────────
# CONSTANTS - GOLD (XAU/USD) SCALPING
# ─────────────────────────────────────────────

# Minimum combined score to fire a signal (out of ~20)
MIN_SIGNAL_SCORE   = 5.0

# Real-world Scalping Risk/Reward settings for Gold (XAU/USD)
# حداقل و حداکثر فاصله حد ضرر برای جلوگیری از استاپ‌خوردن زودهنگام در نویز بازار
SCALP_SL_MIN_USD   = 3.00    # حداقل فاصله حد ضرر معتبر (۳۰ پیپ)
SCALP_SL_MAX_USD   = 8.50    # حداکثر فاصله حد ضرر مجاز اسکلپ (۸۵ پیپ)
SCALP_TP1_RATIO    = 1.40    # نسبت تارگت اول: 1:1.4
SCALP_TP2_RATIO    = 2.30    # نسبت تارگت دوم: 1:2.3
SCALP_TP3_RATIO    = 3.60    # نسبت تارگت سوم: 1:3.6

MIN_RR_RATIO       = 1.2     # Minimum Risk:Reward ratio


# ─────────────────────────────────────────────
# CONFLUENCE SCORING ENGINE
# ─────────────────────────────────────────────

def compute_confluence_score(ta_report: dict, fa_report: dict, session_report: dict, ict_report: dict = None) -> dict:
    """
    Aggregate all analysis into a single directional score.

    Score components:
      Technical:    daily(×3) + H4(×2.5) + H1(×2) + M15(×1)  → weighted TA score
      Fundamental:  fa_report total_score × 1.5
      Session:      timing score × 0.5
      MTF trend:    alignment bonus

    Returns dict with total_score, buy_score, sell_score, details.
    """
    details    = []
    buy_score  = 0.0
    sell_score = 0.0

    # ── Technical scores ──
    ta_scores = ta_report.get("scores", {})
    weights   = {"daily": 3.0, "h4": 2.5, "h1": 2.0, "m15": 1.0}

    for tf, weight in weights.items():
        ts = ta_scores.get(tf, {})
        raw = ts.get("score", 0)
        if raw > 0:
            buy_score  += raw * weight
            details.append(f"TA {tf.upper()}: +{raw:.1f} × {weight} = +{raw*weight:.1f} (صعودی)")
        elif raw < 0:
            sell_score += abs(raw) * weight
            details.append(f"TA {tf.upper()}: {raw:.1f} × {weight} = -{abs(raw)*weight:.1f} (نزولی)")
        else:
            details.append(f"TA {tf.upper()}: خنثی")

    # ── MTF Trend bonus ──
    mtf = ta_report.get("mtf_trend", {})
    overall = mtf.get("overall", "mixed")
    if overall == "bullish":
        buy_score  += 2
        details.append("MTF Trend: هماهنگی صعودی در تایم‌فریم‌های کلیدی +2")
    elif overall == "bearish":
        sell_score += 2
        details.append("MTF Trend: هماهنگی نزولی در تایم‌فریم‌های کلیدی +2")
    else:
        details.append("MTF Trend: تضاد تایم‌فریم‌ها (mixed)")

    # ── Candlestick pattern bonus ──
    patterns_h1  = ta_report.get("patterns", {}).get("h1",  [])
    patterns_m15 = ta_report.get("patterns", {}).get("m15", [])
    all_patterns = patterns_h1 + patterns_m15

    for p in all_patterns:
        p_lower = p.lower()
        if "bullish" in p_lower or "hammer" in p_lower:
            buy_score  += 1.5
            details.append(f"Pattern: {p} → +1.5 صعودی")
        elif "bearish" in p_lower or "shooting" in p_lower:
            sell_score += 1.5
            details.append(f"Pattern: {p} → +1.5 نزولی")
        else:
            details.append(f"Pattern: {p} → خنثی")

    # ── Fundamental score ──
    fa_total = fa_report.get("total_score", 0)
    if fa_total > 0:
        buy_score  += fa_total * 1.5
        details.append(f"Fundamental: +{fa_total:.1f} × 1.5 = +{fa_total*1.5:.1f} (صعودی)")
    elif fa_total < 0:
        sell_score += abs(fa_total) * 1.5
        details.append(f"Fundamental: {fa_total:.1f} × 1.5 = -{abs(fa_total)*1.5:.1f} (نزولی)")

    # ── Session timing bonus ──
    timing_score = session_report.get("timing", {}).get("score", 1)
    session_bonus = (timing_score - 1) * 0.5
    if session_bonus > 0:
        buy_score  += session_bonus
        sell_score += session_bonus  # timing helps both directions equally
        details.append(f"Session timing: +{session_bonus:.1f} (هر دو جهت)")
        
    # ── ICT score ──
    if ict_report:
        ict_net = ict_report.get('ict_score', 0)
        # وزن‌دهی منطقی مفاهیم ICT بدون اثر تخریبی و غلبه نامعقول بر سایر تایم‌فریم‌ها
        ict_weighted = max(-10.0, min(10.0, ict_net * 1.5))
        if ict_weighted > 0:
            buy_score += ict_weighted
            details.append(f"ICT Concepts: +{ict_weighted:.1f} (صعودی)")
        elif ict_weighted < 0:
            sell_score += abs(ict_weighted)
            details.append(f"ICT Concepts: -{abs(ict_weighted):.1f} (نزولی)")
        
        for sig in ict_report.get('signals', []):
            if sig not in details:
                details.append(f"ICT Detail: {sig}")

    net_score = buy_score - sell_score
    return {
        "buy_score":  round(buy_score,  2),
        "sell_score": round(sell_score, 2),
        "net_score":  round(net_score,  2),
        "details":    details,
    }


# ─────────────────────────────────────────────
# ENTRY PRICE CALCULATION
# ─────────────────────────────────────────────

def calculate_entry_levels(
    direction:  str,
    current_price: float,
    atr:        float,
    key_levels: dict,
    ta_report:  dict,
    ict_report: dict = None
) -> dict:
    """
    محاسبه سطوح ورود، حد ضرر ساختاری (SL) و اهداف سود (TP) متناسب با نوسانات واقعی طلا (XAU/USD).
    از قراردادن حد ضررهای ساختگی در محدوده نویز بازار اکیداً جلوگیری می‌شود.
    """
    atr_15m = ta_report.get("atr_15m") if ta_report else None
    if atr_15m and atr_15m > 0.5:
        atr_scalp = atr_15m
    elif atr and atr > 0.5:
        atr_scalp = atr * 0.42
    else:
        atr_scalp = 3.50

    min_risk = max(SCALP_SL_MIN_USD, round(atr_scalp * 0.9, 2))
    max_risk = max(SCALP_SL_MAX_USD, round(atr_scalp * 2.2, 2))

    entry = round(current_price, 2)

    swing = key_levels.get("hourly_swing", {}) if key_levels else {}
    support_levels    = swing.get("support", [])
    resistance_levels = swing.get("resistance", [])

    candidate_sl = None

    if direction == "BUY":
        # اولویت ۱: استاپ ساختاری پشت استخر نقدینگی یا کف سویپ شده ICT
        if ict_report:
            buy_sl = ict_report.get("sl_recommendation", {}).get("buy_sl")
            if buy_sl and buy_sl < entry:
                candidate_sl = round(buy_sl - 0.80, 2)
        
        # اولویت ۲: سطح حمایت سوینگ ساعتی
        if candidate_sl is None and support_levels:
            valid_s = [s for s in support_levels if s < entry]
            if valid_s:
                candidate_sl = round(valid_s[0] - 0.50, 2)

        # اولویت ۳: حد ضرر بر مبنای ATR
        if candidate_sl is None:
            candidate_sl = round(entry - max(min_risk, atr_scalp * 1.5), 2)

        risk = round(entry - candidate_sl, 2)
        if risk < min_risk:
            risk = min_risk
            candidate_sl = round(entry - risk, 2)

        # اگر فاصله تا استاپ ساختاری بیشتر از سقف مجاز اسکلپ باشد، ورود دیرهنگام بوده و مردود است
        if risk > max_risk:
            return {
                "entry": entry,
                "sl": candidate_sl,
                "risk_too_high": True,
                "risk_pips": risk,
                "rr1": 0, "rr2": 0, "rr3": 0,
                "atr_used": round(atr_scalp, 2)
            }

        sl = candidate_sl
        tp1 = round(entry + risk * SCALP_TP1_RATIO, 2)
        tp2 = round(entry + risk * SCALP_TP2_RATIO, 2)
        tp3 = round(entry + risk * SCALP_TP3_RATIO, 2)

    else:  # SELL
        # اولویت ۱: استاپ ساختاری پشت استخر نقدینگی یا سقف سویپ شده ICT
        if ict_report:
            sell_sl = ict_report.get("sl_recommendation", {}).get("sell_sl")
            if sell_sl and sell_sl > entry:
                candidate_sl = round(sell_sl + 0.80, 2)

        # اولویت ۲: سطح مقاومت سوینگ ساعتی
        if candidate_sl is None and resistance_levels:
            valid_r = [r for r in resistance_levels if r > entry]
            if valid_r:
                candidate_sl = round(valid_r[0] + 0.50, 2)

        # اولویت ۳: حد ضرر بر مبنای ATR
        if candidate_sl is None:
            candidate_sl = round(entry + max(min_risk, atr_scalp * 1.5), 2)

        risk = round(candidate_sl - entry, 2)
        if risk < min_risk:
            risk = min_risk
            candidate_sl = round(entry + risk, 2)

        # اگر فاصله تا استاپ ساختاری بیشتر از سقف مجاز اسکلپ باشد، ورود دیرهنگام بوده و مردود است
        if risk > max_risk:
            return {
                "entry": entry,
                "sl": candidate_sl,
                "risk_too_high": True,
                "risk_pips": risk,
                "rr1": 0, "rr2": 0, "rr3": 0,
                "atr_used": round(atr_scalp, 2)
            }

        sl = candidate_sl
        tp1 = round(entry - risk * SCALP_TP1_RATIO, 2)
        tp2 = round(entry - risk * SCALP_TP2_RATIO, 2)
        tp3 = round(entry - risk * SCALP_TP3_RATIO, 2)

    actual_risk = round(abs(entry - sl), 2)
    rr1 = round(abs(tp1 - entry) / actual_risk, 2) if actual_risk > 0 else 0
    rr2 = round(abs(tp2 - entry) / actual_risk, 2) if actual_risk > 0 else 0
    rr3 = round(abs(tp3 - entry) / actual_risk, 2) if actual_risk > 0 else 0

    return {
        "entry":         entry,
        "sl":            sl,
        "tp1":           tp1,
        "tp2":           tp2,
        "tp3":           tp3,
        "risk_pips":     actual_risk,
        "risk_too_high": False,
        "rr1":           rr1,
        "rr2":           rr2,
        "rr3":           rr3,
        "atr_used":      round(atr_scalp, 2),
    }



# ─────────────────────────────────────────────
# SIGNAL CONFIDENCE & QUALITY
# ─────────────────────────────────────────────

def assess_signal_quality(
    confluence:    dict,
    levels:        dict,
    session_report: dict,
    fa_report:     dict
) -> dict:
    score     = abs(confluence["net_score"])
    rr1       = levels.get("rr1", 0)
    timing    = session_report.get("timing", {}).get("score", 1)
    cal_risk  = fa_report.get("components", {}).get("calendar", {}).get("risk_level", "low")
    fa_bias   = fa_report.get("bias", "neutral")

    grade_score = 0

    if score >= 18:    grade_score += 4
    elif score >= 12:  grade_score += 3
    elif score >= 7:   grade_score += 2
    else:              grade_score += 1

    if rr1 >= 2.5:     grade_score += 3
    elif rr1 >= 2.0:   grade_score += 2
    elif rr1 >= 1.5:   grade_score += 1

    if timing >= 4:    grade_score += 2
    elif timing >= 3:  grade_score += 1

    if cal_risk in ("very_high",): grade_score -= 3
    elif cal_risk == "high":       grade_score -= 1

    if "bullish" in fa_bias or "bearish" in fa_bias:
        grade_score += 1

    if grade_score >= 8:
        grade      = "A"
        confidence = min(95, 70 + grade_score * 2)
        label      = "🟢 سیگنال قوی — قابل معامله"
    elif grade_score >= 5:
        grade      = "B"
        confidence = min(80, 55 + grade_score * 2)
        label      = "🟡 سیگنال خوب — با مدیریت ریسک مناسب"
    elif grade_score >= 3:
        grade      = "C"
        confidence = min(65, 40 + grade_score * 2)
        label      = "🟠 سیگنال ضعیف — حجم کم، احتیاط لازم"
    else:
        grade      = "D"
        confidence = max(20, grade_score * 10)
        label      = "🔴 سیگنال بسیار ضعیف — معامله نکنید"

    warnings = []
    if cal_risk in ("high", "very_high"):
        warnings.append("⚠️ رویداد اقتصادی پراهمیت نزدیک است — حجم را کاهش دهید")
    if timing <= 2:
        warnings.append("⚠️ زمان‌بندی سشن ضعیف — بهتر است صبر کنید")
    if rr1 < MIN_RR_RATIO:
        warnings.append(f"⚠️ نسبت R:R پایین ({rr1}) — زیر حد قابل قبول")
    if fa_bias == "neutral":
        warnings.append("⚠️ فاندامنتال خنثی — سیگنال تکنیکال خالص")

    return {
        "grade":      grade,
        "confidence": confidence,
        "label":      label,
        "warnings":   warnings,
    }


# ─────────────────────────────────────────────
# POSITION SIZING GUIDANCE
# ─────────────────────────────────────────────

def calculate_position_size(entry: float, sl: float, account_balance: float = 10000,
                              risk_pct: float = 1.0) -> dict:
    risk_amount = account_balance * (risk_pct / 100)
    sl_distance = abs(entry - sl)

    if sl_distance <= 0:
        return {"lots": 0, "risk_usd": 0}

    lots = risk_amount / (sl_distance * 100)
    lots = round(lots, 2)

    return {
        "lots":           lots,
        "risk_usd":       round(risk_amount, 2),
        "sl_distance":    round(sl_distance, 2),
        "note":           f"بر اساس حساب ${account_balance:,.0f} با ریسک {risk_pct}%"
    }


def _check_cooldown(direction: str, utc_time: datetime) -> str | None:
    """
    بررسی کول‌داون و جلوگیری از تکرار اشتباهات گذشته یا معامله شتاب‌زده پس از استاپ‌لاس.
    """
    try:
        from modules.weekly_tracker import _load_weekly_state
        state = _load_weekly_state()
        signals = state.get("signals", [])
        if not signals:
            return None

        # ۱. بررسی اگر پوزیشن فعال در همین جهت هنوز باز است
        active = [s for s in signals if s.get("direction") == direction and s.get("status") == "ACTIVE"]
        if active:
            last_act = active[-1]
            return f"⚡ پوزیشن قبلی [{last_act['id']}] در جهت {direction} هنوز فعال است — صبر برای تعیین تکلیف معامله جاری"

        # ۲. بررسی کول‌داون پس از استاپ‌لاس در این جهت
        same_dir = [s for s in signals if s.get("direction") == direction]
        if same_dir:
            last_sig = same_dir[-1]
            if last_sig.get("status") == "SL_HIT":
                try:
                    sig_time = datetime.strptime(last_sig["timestamp_utc"], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=pytz.UTC)
                    elapsed = (utc_time - sig_time).total_seconds() / 60.0
                    if elapsed < 35.0:
                        return f"⛔ توقف موقت (Cooldown): آخرین سیگنال {direction} با استاپ مواجه شده ({int(elapsed)} دقیقه پیش) — صبر تا تثبیت ساختار جدید"
                except Exception:
                    pass
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────
# MAIN SIGNAL GENERATOR
# ─────────────────────────────────────────────

def generate_signal(snapshot: dict, utc_time: datetime = None, ta_report: dict = None, fa_report: dict = None, session_report: dict = None) -> dict:
    if utc_time is None:
        utc_time = datetime.now(pytz.UTC)

    if ta_report is None:
        ta_report      = full_technical_report(snapshot)
    if fa_report is None:
        fa_report      = full_fundamental_report(snapshot)
    if session_report is None:
        session_report = full_session_report(snapshot, utc_time)

    current_price = snapshot.get("current", {}).get("price")
    gold_1h = snapshot.get("gold_1h", pd.DataFrame())
    gold_15m = snapshot.get("gold_15m", pd.DataFrame())
    gold_4h = snapshot.get("gold_4h", pd.DataFrame())
    gold_daily = snapshot.get("gold_daily", pd.DataFrame())
    
    if current_price is None:
        current_price = float(gold_1h["Close"].iloc[-1]) if not gold_1h.empty else 1900.0

    atr        = ta_report.get("atr_1h")
    key_levels = ta_report.get("key_levels", {})
    update_weekly_signal_statuses(current_price)
    
    ict_report = full_ict_report(gold_1h, gold_15m, gold_4h, gold_daily, utc_time)

    confluence = compute_confluence_score(ta_report, fa_report, session_report, ict_report)

    net   = confluence["net_score"]
    buy_s = confluence["buy_score"]
    sell_s= confluence["sell_score"]

    session_key = session_report.get("current_session", {}).get("key", "")
    cal_risk    = fa_report.get("components", {}).get("calendar", {}).get("risk_level", "low")

    daily_status = get_daily_status()

    market_st = session_report.get("market_status", {})
    if not market_st:
        market_st = session_report.get("current_session", {}).get("market_status", {})

    if market_st and not market_st.get("can_trade", True):
        badge = market_st.get("badge_text", "🔴 بازار بسته است")
        reason = market_st.get("reason", "بازار در این ساعت بسته است")
        return _build_wait_signal(
            f"{badge} — {reason}",
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )

    if session_key in ("weekend_closed", "daily_break", "dead_zone"):
        return _build_wait_signal(
            "⛔ بازار بسته یا کم‌نقدینگی است — امکان ثبت پوزیشن وجود ندارد",
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )

    if cal_risk == "very_high" and abs(net) < 5:
        return _build_wait_signal(
            "⚠️ رویداد اقتصادی بسیار پراهمیت نزدیک — صبر کنید",
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )
        
    # فیلتر کیل‌زون و تاییدیه اسمارت مانی (هوشمند و بدون بن‌بست)
    in_kz = ict_report.get("kill_zone", {}).get("in_kill_zone", False)
    ict_net_score = ict_report.get("ict_score", 0)
    conf_count = ict_report.get("confirmation_count", 0)
    
    # خارج از کیل‌زون: تنها در صورت نبود مومنتوم و هماهنگی قوی صبر می‌کنیم
    if not in_kz and abs(ict_net_score) < 3.0 and abs(net) < 7.5:
        return _build_wait_signal(
            "⛔ خارج از Kill Zone اسمارت مانی — حجم بازار برای اسکلپ سریع مناسب نیست",
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )
        
    # تاییدیه اسمارت مانی: حداقل ۱ فاکتور معتبر کافی است
    if conf_count < 1 and abs(ict_net_score) < 4.0 and abs(net) < 8.0:
        return _build_wait_signal(
            "⛔ عدم تایید کافی از سوی مفاهیم اسمارت مانی (Smart Money)",
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )

    total_score = buy_s + sell_s
    buy_ratio  = (buy_s  / total_score) if total_score > 0 else 0
    sell_ratio = (sell_s / total_score) if total_score > 0 else 0

    if net >= MIN_SIGNAL_SCORE:
        direction = "BUY"
    elif net <= -MIN_SIGNAL_SCORE:
        direction = "SELL"
    elif buy_ratio >= 0.65 and net >= 3.5:
        direction = "BUY"
    elif sell_ratio >= 0.65 and net <= -3.5:
        direction = "SELL"
    else:
        return _build_wait_signal(
            f"📊 سیگنال واضحی وجود ندارد (score: {net:.1f}). صبر برای تأیید بیشتر",
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )

    # ── فیلتر ۱: منطق اسمارت مانی (ICT Zone Filter) — عدم خرید در سقف افراطی و عدم فروش در کف افراطی ──
    pd_info = ict_report.get("premium_discount", {}) if ict_report else {}
    pd_zone = pd_info.get("zone")
    pd_pct  = pd_info.get("current_pct", 0.5)
    dol_info = ict_report.get("draw_on_liquidity", {}) if ict_report else {}
    dol_bias = dol_info.get("bias", "neutral")
    ms_trend = ict_report.get("market_structure", {}).get("trend", "ranging")

    # فروش در دیسکانت: فقط در کف افراطی (<0.12) که خطر بازگشت وجود دارد رد می‌شود
    if direction == "SELL" and pd_zone == "discount":
        if pd_pct < 0.12 and dol_bias != "bearish" and ms_trend != "bearish":
            return _build_wait_signal(
                "⛔ رد سیگنال فروش: قیمت در کف افراطی (Deep Discount) است — خطر شدید خرید نهادی و برگشت قیمت",
                ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
            )

    # خرید در پریمیوم: فقط در سقف افراطی (>0.88) که خطر اصلاح وجود دارد رد می‌شود
    if direction == "BUY" and pd_zone == "premium":
        if pd_pct > 0.88 and dol_bias != "bullish" and ms_trend != "bullish":
            return _build_wait_signal(
                "⛔ رد سیگنال خرید: قیمت در سقف افراطی (Deep Premium) است — خطر شدید عرضه سنگین و اصلاح قیمت",
                ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
            )

    # ── فیلتر ۲: هماهنگی با روند H1 و مومنتوم MACD (تعدیل شده برای اسکلپ) ──
    mtf = ta_report.get("mtf_trend", {})
    h1_trend = mtf.get("h1", {}).get("direction", "unknown")
    lv = ta_report.get("latest_values", {})
    macd_hist = lv.get("MACD_Hist")

    trend_conflict_penalty = 0
    if direction == "SELL" and h1_trend == "bullish" and macd_hist is not None and macd_hist > 1.5:
        if abs(net) < 14: # Only block if the setup is weak
            return _build_wait_signal(
                f"⛔ رد سیگنال فروش: روند قوی صعودی H1 و مومنتوم MACD (+{macd_hist:.2f})",
                ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
            )
        trend_conflict_penalty = 15
        
    if direction == "BUY" and h1_trend == "bearish" and macd_hist is not None and macd_hist < -1.5:
        if abs(net) < 14: # Only block if the setup is weak
            return _build_wait_signal(
                f"⛔ رد سیگنال خرید: روند قوی نزولی H1 و مومنتوم MACD ({macd_hist:.2f})",
                ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
            )
        trend_conflict_penalty = 15

    # ── فیلتر ۳: سطوح ورود و حد ضرر ساختاری ──
    levels = calculate_entry_levels(
        direction, current_price, atr, key_levels, ta_report, ict_report
    )

    if levels.get("risk_too_high"):
        return _build_wait_signal(
            f"⚠️ حد ضرر ساختاری خارج از محدوده مجاز اسکلپ است ({levels.get('risk_pips', 0):.2f}$) — ورود در این سطح به منزله تعقیب قیمت است؛ صبر برای پولبک به منطقه بهینه ورود (OTE)",
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )

    if levels["rr1"] < MIN_RR_RATIO:
        return _build_wait_signal(
            f"⚠️ نسبت ریسک/ریوارد غیرقابل قبول (R:R={levels['rr1']}) — حداقل نسبت مجاز 1:{MIN_RR_RATIO} است",
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )

    # ── فیلتر ۴: ارزیابی کیفیت سیگنال و حذف رتبه‌های ضعیف (D) ──
    quality = assess_signal_quality(confluence, levels, session_report, fa_report)

    # ── اعمال پنالتی خلاف جهت روند روی درصد اطمینان ──
    quality["confidence"] = max(0, quality["confidence"] - trend_conflict_penalty)
    # اگر بعد از پنالتی، گرید یا درصد اطمینان افت کرد، آن را داون‌گرید می‌کنیم
    if trend_conflict_penalty > 0 and quality["grade"] in ("A", "A+"):
        quality["grade"] = "B"
    elif trend_conflict_penalty > 0 and quality["grade"] in ("B", "B+"):
        quality["grade"] = "C"

    if quality["grade"] == "D" or quality["confidence"] < 40:
        return _build_wait_signal(
            f"⚠️ کیفیت سیگنال برای معامله کافی نیست (رتبه {quality['grade']} / اطمینان {quality['confidence']}٪)",
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )

    # ── فیلتر ۵: بررسی کول‌داون و جلوگیری از معامله انتقامی پس از استاپ ──
    cooldown_msg = _check_cooldown(direction, utc_time)
    if cooldown_msg:
        return _build_wait_signal(
            cooldown_msg,
            ta_report, fa_report, session_report, utc_time, confluence, daily_status, ict_report
        )

    reasoning = _build_reasoning(
        direction, ta_report, fa_report, session_report, confluence, levels, ict_report
    )

    sizing = calculate_position_size(levels["entry"], levels["sl"])

    sig_result = {
        "signal":        direction,
        "grade":         quality["grade"],
        "confidence":    quality["confidence"],
        "label":         f"اسکلپ طلا ({quality['grade']})",
        "entry":         levels["entry"],
        "sl":            levels["sl"],
        "tp1":           levels["tp1"],
        "tp2":           levels["tp2"],
        "tp3":           levels["tp3"],
        "rr1":           levels["rr1"],
        "rr2":           levels["rr2"],
        "rr3":           levels["rr3"],
        "risk_pips":     levels["risk_pips"],
        "atr":           levels["atr_used"],
        "position_size": sizing,
        "net_score":     confluence["net_score"],
        "buy_score":     confluence["buy_score"],
        "sell_score":    confluence["sell_score"],
        "score_details": confluence["details"],
        "reasoning":     reasoning,
        "warnings":      quality["warnings"],
        "ta_report":     ta_report,
        "fa_report":     fa_report,
        "session_report":session_report,
        "ict_report":    ict_report,
        "ict_summary":   ict_report.get("signals", []) if ict_report else [],
        "daily_scalp":   daily_status,
        "timestamp":     utc_time.strftime("%Y-%m-%d %H:%M UTC"),
    }

    weekly_rec = record_weekly_signal(sig_result, utc_time=utc_time)
    if weekly_rec:
        sig_result["weekly_id"] = weekly_rec["id"]
        sig_result["label"] = f"اسکلپ طلا [{weekly_rec['id']}]"
        sig_result["weekly_record"] = weekly_rec

    export_signal_to_bridge(sig_result)

    return sig_result


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _build_wait_signal(reason: str, ta_report, fa_report, session_report,
                       utc_time, confluence=None, daily_status=None, ict_report=None) -> dict:
    if daily_status is None:
        daily_status = get_daily_status()

    buy_score  = confluence["buy_score"]  if confluence else 0
    sell_score = confluence["sell_score"] if confluence else 0
    net_score  = confluence["net_score"]  if confluence else 0
    details    = confluence["details"]    if confluence else []

    return {
        "signal":        "WAIT",
        "grade":         "D",
        "confidence":    0,
        "label":         reason,
        "entry":         None,
        "sl":            None,
        "tp1":           None,
        "tp2":           None,
        "tp3":           None,
        "rr1":           0,
        "rr2":           0,
        "rr3":           0,
        "risk_pips":     0,
        "atr":           ta_report.get("atr_1h") if ta_report else None,
        "position_size": None,
        "net_score":     net_score,
        "buy_score":     buy_score,
        "sell_score":    sell_score,
        "score_details": details,
        "reasoning":     [reason],
        "warnings":      [],
        "ta_report":     ta_report,
        "fa_report":     fa_report,
        "session_report":session_report,
        "ict_report":    ict_report,
        "ict_summary":   ict_report.get("signals", []) if ict_report else [],
        "daily_scalp":   daily_status,
        "timestamp":     utc_time.strftime("%Y-%m-%d %H:%M UTC"),
    }


def _build_reasoning(direction, ta_report, fa_report, session_report,
                      confluence, levels, ict_report=None) -> list:
    lines = []

    emoji = "🟢" if direction == "BUY" else "🔴"
    lines.append(f"{emoji} سیگنال {direction}: امتیاز کلی {confluence['net_score']:.1f}")

    if ict_report:
        lines.append(f"🧠 اسمارت مانی (ICT): {ict_report.get('confirmation_count', 0)} تاییدیه")
        for sig in ict_report.get("signals", []):
            lines.append(f"   • {sig}")
        sl_rec = ict_report.get("sl_recommendation", {})
        if direction == "BUY" and sl_rec.get("buy_sl"):
            lines.append(f"   • استاپ لاس خریدار پشت نقدینگی: {sl_rec['buy_sl']}")
        elif direction == "SELL" and sl_rec.get("sell_sl"):
            lines.append(f"   • استاپ لاس فروشنده پشت نقدینگی: {sl_rec['sell_sl']}")

    mtf     = ta_report.get("mtf_trend", {})
    overall = mtf.get("overall", "mixed")
    d_trend = mtf.get("daily",  {}).get("direction", "?")
    h4_trend= mtf.get("h4",    {}).get("direction", "?")
    h1_trend= mtf.get("h1",    {}).get("direction", "?")
    lines.append(f"📊 روند چندتایم‌فریمی: روزانه={d_trend} | H4={h4_trend} | H1={h1_trend} → {overall}")

    lv = ta_report.get("latest_values", {})
    rsi = lv.get("RSI")
    macd_h = lv.get("MACD_Hist")
    ema200 = lv.get("EMA_200")
    price  = lv.get("Close")
    if rsi:
        rsi_state = "اشباع فروش" if rsi < 30 else ("اشباع خرید" if rsi > 70 else "خنثی")
        lines.append(f"📈 RSI: {rsi:.1f} ({rsi_state})")
    if macd_h:
        macd_state = "صعودی" if macd_h > 0 else "نزولی"
        lines.append(f"📈 MACD Histogram: {macd_h:.2f} ({macd_state})")
    if ema200 and price:
        pos = "بالاتر" if price > ema200 else "پایین‌تر"
        lines.append(f"📈 قیمت {pos} از EMA200 ({ema200:.1f})")

    patterns = ta_report.get("patterns", {})
    all_p = patterns.get("h1", []) + patterns.get("m15", [])
    if all_p:
        lines.append(f"🕯️ الگوهای کندلی: {' | '.join(all_p)}")

    entry = levels.get("entry")
    sl    = levels.get("sl")
    tp1   = levels.get("tp1")
    if entry:
        lines.append(f"🎯 ورود: {entry} | حد ضرر: {sl} | هدف اول: {tp1}")
        lines.append(f"📐 نسبت R:R → TP1: 1:{levels.get('rr1',0)} | TP2: 1:{levels.get('rr2',0)} | TP3: 1:{levels.get('rr3',0)}")

    fa_bias   = fa_report.get("bias_label", "")
    fa_score  = fa_report.get("total_score", 0)
    lines.append(f"💰 فاندامنتال: {fa_bias} (امتیاز: {fa_score:.1f})")

    sess_name   = session_report.get("current_session", {}).get("name", "")
    timing_adv  = session_report.get("timing", {}).get("advice", "")
    if sess_name: lines.append(f"⏰ سشن فعال: {sess_name}")
    if timing_adv:lines.append(f"⏰ {timing_adv}")

    return lines
