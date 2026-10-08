"""
Fundamental Analysis Module
-----------------------------
Analyzes macro-economic factors that drive gold price:
  - US Dollar Index (DXY) correlation
  - US 10-Year Treasury Yield
  - S&P 500 (risk-on / risk-off)
  - News sentiment (from data_fetcher)
  - Economic calendar events
  - Geopolitical risk score
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz


# ─────────────────────────────────────────────
# DXY ANALYSIS
# ─────────────────────────────────────────────

def analyze_dxy(dxy_df: pd.DataFrame) -> dict:
    """
    Analyze US Dollar Index.
    Gold has strong INVERSE correlation with DXY (~-0.85).
    Strong DXY  → bearish for gold
    Weak DXY    → bullish for gold
    """
    if dxy_df is None or dxy_df.empty or len(dxy_df) < 5:
        return {
            "trend":     "unknown",
            "signal":    "neutral",
            "score":     0,
            "current":   None,
            "change_1d": None,
            "note":      "DXY data unavailable"
        }

    current   = float(dxy_df["Close"].iloc[-1])
    prev_day  = float(dxy_df["Close"].iloc[-24]) if len(dxy_df) >= 24 else float(dxy_df["Close"].iloc[0])
    prev_week = float(dxy_df["Close"].iloc[-120]) if len(dxy_df) >= 120 else float(dxy_df["Close"].iloc[0])

    change_1d = round(((current - prev_day) / prev_day) * 100, 3)
    change_1w = round(((current - prev_week) / prev_week) * 100, 3)

    # EMA trend on DXY
    closes = dxy_df["Close"]
    ema20  = closes.ewm(span=20).mean().iloc[-1]
    ema50  = closes.ewm(span=50).mean().iloc[-1]

    if current < ema20 < ema50:
        dxy_trend = "downtrend"  # Dollar weakening → gold bullish
    elif current > ema20 > ema50:
        dxy_trend = "uptrend"    # Dollar strengthening → gold bearish
    else:
        dxy_trend = "sideways"

    # Map DXY trend to gold signal (inverse)
    if dxy_trend == "downtrend":
        signal = "bullish_gold"
        score  = 2
    elif dxy_trend == "uptrend":
        signal = "bearish_gold"
        score  = -2
    else:
        # Check daily change
        if change_1d < -0.2:
            signal = "bullish_gold"
            score  = 1
        elif change_1d > 0.2:
            signal = "bearish_gold"
            score  = -1
        else:
            signal = "neutral"
            score  = 0

    return {
        "trend":     dxy_trend,
        "signal":    signal,
        "score":     score,
        "current":   round(current, 3),
        "change_1d": change_1d,
        "change_1w": change_1w,
        "ema20":     round(float(ema20), 3),
        "ema50":     round(float(ema50), 3),
        "note":      _dxy_interpretation(dxy_trend, change_1d)
    }


def _dxy_interpretation(trend: str, change_1d: float) -> str:
    msgs = {
        "downtrend": "دلار در روند نزولی است — تقویت‌کننده طلا",
        "uptrend":   "دلار در روند صعودی است — فشار نزولی روی طلا",
        "sideways":  "دلار در تثبیت است — تأثیر محدود روی طلا",
    }
    base = msgs.get(trend, "وضعیت دلار نامشخص")
    if abs(change_1d) > 0.3:
        direction = "کاهش" if change_1d < 0 else "افزایش"
        base += f" | تغییر روزانه {direction} {abs(change_1d):.2f}%"
    return base


# ─────────────────────────────────────────────
# TREASURY YIELD ANALYSIS
# ─────────────────────────────────────────────

def analyze_yields(yield_data: dict) -> dict:
    """
    US 10-Year Treasury Yield analysis.
    Rising yields typically → bearish for gold (opportunity cost of holding gold rises).
    Falling yields typically → bullish for gold.
    """
    if not yield_data or yield_data.get("yield") is None:
        return {
            "signal":  "neutral",
            "score":   0,
            "current": None,
            "change":  None,
            "note":    "Yield data unavailable"
        }

    current = yield_data["yield"]
    change  = yield_data.get("change", 0) or 0

    # Historical context: above 4.5% is restrictive, below 3.5% is supportive for gold
    if current > 4.8:
        score  = -2
        signal = "bearish_gold"
        note   = f"بازده ۱۰ ساله بالا ({current}%) — فشار نزولی قوی روی طلا"
    elif current > 4.2:
        score  = -1
        signal = "mild_bearish"
        note   = f"بازده ۱۰ ساله بالا ({current}%) — فشار نزولی ملایم روی طلا"
    elif current < 3.5:
        score  = 2
        signal = "bullish_gold"
        note   = f"بازده ۱۰ ساله پایین ({current}%) — حمایت صعودی از طلا"
    elif current < 4.0:
        score  = 1
        signal = "mild_bullish"
        note   = f"بازده ۱۰ ساله متعادل ({current}%) — محیط نسبتاً مناسب برای طلا"
    else:
        score  = 0
        signal = "neutral"
        note   = f"بازده ۱۰ ساله خنثی ({current}%)"

    # Additional score for direction of change
    if change < -0.05:
        score += 1
        note  += " | بازده در حال کاهش — مثبت برای طلا"
    elif change > 0.05:
        score -= 1
        note  += " | بازده در حال افزایش — منفی برای طلا"

    return {
        "signal":  signal,
        "score":   score,
        "current": current,
        "change":  change,
        "note":    note
    }


# ─────────────────────────────────────────────
# RISK SENTIMENT (S&P 500)
# ─────────────────────────────────────────────

def analyze_risk_sentiment(sp500_df: pd.DataFrame) -> dict:
    """
    S&P 500 as risk-on/risk-off gauge.
    Risk-off (falling equities) → demand for gold safe haven → bullish
    Risk-on (rising equities)   → less demand for gold → mild bearish
    """
    if sp500_df is None or sp500_df.empty or len(sp500_df) < 5:
        return {
            "mode":   "unknown",
            "signal": "neutral",
            "score":  0,
            "note":   "SP500 data unavailable"
        }

    closes   = sp500_df["Close"]
    current  = float(closes.iloc[-1])
    prev_5d  = float(closes.iloc[-5])
    prev_20d = float(closes.iloc[-20]) if len(closes) >= 20 else float(closes.iloc[0])

    change_5d  = round(((current - prev_5d) / prev_5d) * 100, 2)
    change_20d = round(((current - prev_20d) / prev_20d) * 100, 2)

    if change_5d < -2.0:
        mode   = "risk-off"
        signal = "bullish_gold"
        score  = 2
        note   = f"S&P500 در ریزش ۵ روزه ({change_5d:.1f}%) — حالت risk-off — مثبت برای طلا"
    elif change_5d < -0.5:
        mode   = "mild risk-off"
        signal = "mild_bullish"
        score  = 1
        note   = f"S&P500 ضعیف ({change_5d:.1f}%) — تمایل به safe haven"
    elif change_5d > 2.0:
        mode   = "risk-on"
        signal = "mild_bearish"
        score  = -1
        note   = f"S&P500 در صعود ({change_5d:.1f}%) — حالت risk-on — فشار خفیف روی طلا"
    else:
        mode   = "neutral"
        signal = "neutral"
        score  = 0
        note   = f"S&P500 خنثی ({change_5d:.1f}%) — تأثیر محدود روی طلا"

    return {
        "mode":      mode,
        "signal":    signal,
        "score":     score,
        "sp500":     round(current, 1),
        "change_5d": change_5d,
        "change_20d":change_20d,
        "note":      note
    }


# ─────────────────────────────────────────────
# ECONOMIC CALENDAR IMPACT
# ─────────────────────────────────────────────

def analyze_calendar_impact(events: list) -> dict:
    """
    Assess upcoming economic events and their potential gold impact.
    High-impact USD events are most critical.
    """
    if not events:
        return {
            "risk_level":    "low",
            "score":         0,
            "upcoming":      [],
            "note":          "رویداد اقتصادی مهمی ثبت نشده"
        }

    high_impact_usd = []
    medium_impact   = []

    gold_moving_events = [
        "cpi", "pce", "nfp", "non-farm", "fomc", "federal reserve",
        "fed rate", "interest rate", "gdp", "unemployment", "jobs",
        "inflation", "treasury", "powell"
    ]

    for event in events:
        title   = event.get("title", "").lower()
        country = event.get("country", "").upper()
        impact  = event.get("impact", "").lower()

        is_gold_relevant = any(kw in title for kw in gold_moving_events)

        if impact == "high" and (country == "USD" or country == "US"):
            high_impact_usd.append(event)
        elif is_gold_relevant:
            medium_impact.append(event)

    if len(high_impact_usd) >= 3:
        risk_level = "very_high"
        score      = -1   # uncertainty → wait for news
        note       = f"⚠️ {len(high_impact_usd)} رویداد بسیار پراهمیت USD این هفته — ریسک معامله بالا"
    elif len(high_impact_usd) >= 1:
        risk_level = "high"
        score      = 0
        note       = f"⚠️ {len(high_impact_usd)} رویداد پراهمیت USD — مراقب نوسانات باشید"
    elif len(medium_impact) >= 1:
        risk_level = "medium"
        score      = 0
        note       = f"رویدادهای میان‌اهمیت در تقویم موجود است"
    else:
        risk_level = "low"
        score      = 1   # calm calendar → trend continuation likely
        note       = "تقویم اقتصادی آرام — احتمال ادامه روند فعلی"

    upcoming = (high_impact_usd + medium_impact)[:5]

    return {
        "risk_level":  risk_level,
        "score":       score,
        "upcoming":    upcoming,
        "note":        note
    }


# ─────────────────────────────────────────────
# GEOPOLITICAL RISK
# ─────────────────────────────────────────────

def analyze_geopolitical_risk(news_items: list) -> dict:
    """
    Score geopolitical risk level from news headlines.
    High geo-risk → safe-haven demand → bullish gold.
    """
    geo_keywords = [
        "war", "conflict", "military", "attack", "strike", "missile",
        "invasion", "sanction", "embargo", "nuclear", "tension",
        "crisis", "escalat", "iran", "russia", "china taiwan",
        "middle east", "north korea", "terrorism"
    ]

    risk_score = 0
    triggers   = []

    for item in news_items:
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        for kw in geo_keywords:
            if kw in text:
                risk_score += 1
                triggers.append(kw)
                break   # count once per article

    if risk_score >= 5:
        level   = "critical"
        signal  = "strong_bullish"
        score   = 3
        note    = "🔴 ریسک ژئوپلیتیکی بسیار بالا — تقاضای قوی safe haven برای طلا"
    elif risk_score >= 3:
        level   = "high"
        signal  = "bullish"
        score   = 2
        note    = "🟠 ریسک ژئوپلیتیکی بالا — حمایت از طلا به عنوان پناهگاه"
    elif risk_score >= 1:
        level   = "moderate"
        signal  = "mild_bullish"
        score   = 1
        note    = "🟡 ریسک ژئوپلیتیکی متوسط — حمایت ملایم از طلا"
    else:
        level   = "low"
        signal  = "neutral"
        score   = 0
        note    = "🟢 ریسک ژئوپلیتیکی پایین"

    return {
        "level":    level,
        "signal":   signal,
        "score":    score,
        "triggers": list(set(triggers))[:5],
        "note":     note
    }


# ─────────────────────────────────────────────
# COMBINED FUNDAMENTAL REPORT
# ─────────────────────────────────────────────

def full_fundamental_report(snapshot: dict) -> dict:
    """
    Generate a complete fundamental analysis report from market snapshot.
    Combines DXY, yields, risk sentiment, calendar, and geopolitical factors.
    """
    dxy_report    = analyze_dxy(snapshot.get("dxy", pd.DataFrame()))
    yield_report  = analyze_yields(snapshot.get("us10y", {}))
    risk_report   = analyze_risk_sentiment(snapshot.get("sp500", pd.DataFrame()))
    cal_report    = analyze_calendar_impact(snapshot.get("calendar", []))
    geo_report    = analyze_geopolitical_risk(snapshot.get("news", []))
    sentiment     = snapshot.get("sentiment", {})

    # Aggregate fundamental score
    total_score = (
        dxy_report["score"]   * 1.5 +   # DXY is most correlated
        yield_report["score"] * 1.2 +   # Yields second most important
        risk_report["score"]  * 1.0 +
        cal_report["score"]   * 0.5 +
        geo_report["score"]   * 1.0 +
        (1 if sentiment.get("sentiment") == "bullish" else
        -1 if sentiment.get("sentiment") == "bearish" else 0)
    )

    if total_score >= 4:
        fundamental_bias = "strongly_bullish"
        bias_label       = "🟢 فاندامنتال قوی صعودی"
    elif total_score >= 1.5:
        fundamental_bias = "bullish"
        bias_label       = "🟢 فاندامنتال صعودی"
    elif total_score <= -4:
        fundamental_bias = "strongly_bearish"
        bias_label       = "🔴 فاندامنتال قوی نزولی"
    elif total_score <= -1.5:
        fundamental_bias = "bearish"
        bias_label       = "🔴 فاندامنتال نزولی"
    else:
        fundamental_bias = "neutral"
        bias_label       = "⚪ فاندامنتال خنثی"

    return {
        "bias":          fundamental_bias,
        "bias_label":    bias_label,
        "total_score":   round(total_score, 2),
        "components": {
            "dxy":          dxy_report,
            "yields":       yield_report,
            "risk_sentiment": risk_report,
            "calendar":     cal_report,
            "geopolitical": geo_report,
            "news_sentiment": sentiment,
        }
    }
