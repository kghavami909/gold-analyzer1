"""
Technical Analysis Module
--------------------------
Calculates all technical indicators and support/resistance levels
for XAU/USD across multiple timeframes.

Indicators:
  - EMA (9, 21, 50, 200)
  - RSI (14)
  - MACD (12, 26, 9)
  - Bollinger Bands (20, 2)
  - ATR (14)  — for SL/TP sizing
  - Stochastic (14, 3, 3)
  - Volume analysis
  - Support & Resistance (pivot points + swing highs/lows)
  - Trend detection (multi-timeframe)
  - Candlestick pattern detection
"""

import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator


# ─────────────────────────────────────────────
# CORE INDICATOR CALCULATIONS
# ─────────────────────────────────────────────

def calculate_emas(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA 9, 21, 50, 200 to dataframe."""
    for period in [9, 21, 50, 200]:
        ema = EMAIndicator(close=df["Close"], window=period)
        df[f"EMA_{period}"] = ema.ema_indicator()
    return df


def calculate_rsi(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """Add RSI to dataframe."""
    rsi = RSIIndicator(close=df["Close"], window=window)
    df["RSI"] = rsi.rsi()
    return df


def calculate_macd(df: pd.DataFrame) -> pd.DataFrame:
    """Add MACD line, signal line, and histogram."""
    macd = MACD(close=df["Close"], window_slow=26, window_fast=12, window_sign=9)
    df["MACD"]        = macd.macd()
    df["MACD_Signal"] = macd.macd_signal()
    df["MACD_Hist"]   = macd.macd_diff()
    return df


def calculate_bollinger(df: pd.DataFrame, window: int = 20, dev: float = 2.0) -> pd.DataFrame:
    """Add Bollinger Bands upper, middle, lower."""
    bb = BollingerBands(close=df["Close"], window=window, window_dev=dev)
    df["BB_Upper"]  = bb.bollinger_hband()
    df["BB_Middle"] = bb.bollinger_mavg()
    df["BB_Lower"]  = bb.bollinger_lband()
    df["BB_Width"]  = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Middle"]
    df["BB_Pct"]    = bb.bollinger_pband()   # 0=lower band, 1=upper band
    return df


def calculate_atr(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """Add ATR — used for dynamic SL/TP calculation."""
    atr = AverageTrueRange(
        high=df["High"], low=df["Low"], close=df["Close"], window=window
    )
    df["ATR"] = atr.average_true_range()
    return df


def calculate_stochastic(df: pd.DataFrame) -> pd.DataFrame:
    """Add Stochastic %K and %D."""
    stoch = StochasticOscillator(
        high=df["High"], low=df["Low"], close=df["Close"],
        window=14, smooth_window=3
    )
    df["Stoch_K"] = stoch.stoch()
    df["Stoch_D"] = stoch.stoch_signal()
    return df


def calculate_obv(df: pd.DataFrame) -> pd.DataFrame:
    """Add On-Balance Volume."""
    if "Volume" in df.columns and df["Volume"].sum() > 0:
        obv = OnBalanceVolumeIndicator(close=df["Close"], volume=df["Volume"])
        df["OBV"] = obv.on_balance_volume()
    else:
        df["OBV"] = 0
    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all indicators to a dataframe. Returns enriched dataframe."""
    if df is None or df.empty or len(df) < 30:
        return df
    df = df.copy()
    df = calculate_emas(df)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_bollinger(df)
    df = calculate_atr(df)
    df = calculate_stochastic(df)
    df = calculate_obv(df)
    return df


# ─────────────────────────────────────────────
# SUPPORT & RESISTANCE
# ─────────────────────────────────────────────

def find_swing_levels(df: pd.DataFrame, lookback: int = 20, num_levels: int = 5) -> dict:
    """
    Identify significant swing high/low levels from recent price history.
    Uses a rolling window to find local extremes.
    """
    if df is None or df.empty or len(df) < lookback * 2:
        return {"support": [], "resistance": []}

    highs = df["High"].values
    lows  = df["Low"].values
    close = df["Close"].values
    current_price = close[-1]

    swing_highs = []
    swing_lows  = []

    for i in range(lookback, len(df) - lookback):
        window_high = max(highs[i - lookback: i + lookback])
        window_low  = min(lows[i - lookback: i + lookback])

        if highs[i] == window_high:
            swing_highs.append(round(highs[i], 2))
        if lows[i] == window_low:
            swing_lows.append(round(lows[i], 2))

    # Cluster nearby levels (within 0.3% of each other)
    swing_highs = _cluster_levels(swing_highs)
    swing_lows  = _cluster_levels(swing_lows)

    # Split into resistance (above price) and support (below price)
    resistance = sorted([h for h in swing_highs if h > current_price])[:num_levels]
    support    = sorted([l for l in swing_lows  if l < current_price], reverse=True)[:num_levels]

    return {
        "support":    support,
        "resistance": resistance,
        "current":    round(current_price, 2)
    }


def _cluster_levels(levels: list, threshold_pct: float = 0.003) -> list:
    """Merge levels that are within threshold_pct of each other."""
    if not levels:
        return []
    levels = sorted(set(levels))
    clustered = [levels[0]]
    for level in levels[1:]:
        if abs(level - clustered[-1]) / clustered[-1] > threshold_pct:
            clustered.append(level)
        else:
            # Replace with average of nearby cluster
            clustered[-1] = round((clustered[-1] + level) / 2, 2)
    return clustered


def calculate_pivot_points(df: pd.DataFrame) -> dict:
    """
    Classic pivot point calculation using previous day's H/L/C.
    Returns PP, S1, S2, S3, R1, R2, R3.
    """
    if df is None or df.empty:
        return {}
    # از آخرین کندل کامل (دیروز) استفاده می‌کنیم، نه کندل جاری ناقص
    idx = -2 if len(df) >= 2 else -1
    last = df.iloc[idx]
    H, L, C = float(last["High"]), float(last["Low"]), float(last["Close"])
    PP = (H + L + C) / 3
    return {
        "PP": round(PP, 2),
        "R1": round(2 * PP - L, 2),
        "R2": round(PP + (H - L), 2),
        "R3": round(H + 2 * (PP - L), 2),
        "S1": round(2 * PP - H, 2),
        "S2": round(PP - (H - L), 2),
        "S3": round(L - 2 * (H - PP), 2),
    }


def find_key_levels(daily_df: pd.DataFrame, hourly_df: pd.DataFrame) -> dict:
    """Combine swing levels + pivot points for a full S/R map."""
    pivots  = calculate_pivot_points(daily_df)
    swings  = find_swing_levels(hourly_df, lookback=15, num_levels=4)
    daily_s = find_swing_levels(daily_df, lookback=10, num_levels=3)

    return {
        "pivot_points":       pivots,
        "hourly_swing":       swings,
        "daily_swing":        daily_s,
    }


# ─────────────────────────────────────────────
# TREND DETECTION
# ─────────────────────────────────────────────

def detect_trend(df: pd.DataFrame) -> dict:
    """
    Determine trend direction using EMA alignment and price structure.
    Returns: 'bullish', 'bearish', or 'sideways' with strength 0-100.
    """
    if df is None or df.empty or "EMA_21" not in df.columns:
        return {"direction": "unknown", "strength": 0}

    last = df.iloc[-1]

    # EMA alignment score
    ema_bull = 0
    ema_bear = 0

    # Price above/below EMAs
    price = last["Close"]
    for ema_col, weight in [("EMA_9", 1), ("EMA_21", 2), ("EMA_50", 3), ("EMA_200", 4)]:
        if ema_col in df.columns and not pd.isna(last.get(ema_col)):
            if price > last[ema_col]:
                ema_bull += weight
            else:
                ema_bear += weight

    # EMA order (9 > 21 > 50 > 200 = strongly bullish)
    if all(col in df.columns for col in ["EMA_9", "EMA_21", "EMA_50"]):
        if last["EMA_9"] > last["EMA_21"] > last["EMA_50"]:
            ema_bull += 3
        elif last["EMA_9"] < last["EMA_21"] < last["EMA_50"]:
            ema_bear += 3

    # Higher highs / higher lows (last 20 candles)
    recent = df.tail(20)
    if len(recent) >= 10:
        first_half = recent.head(10)
        sec_half   = recent.tail(10)
        if sec_half["High"].mean() > first_half["High"].mean() and \
           sec_half["Low"].mean()  > first_half["Low"].mean():
            ema_bull += 2
        elif sec_half["High"].mean() < first_half["High"].mean() and \
             sec_half["Low"].mean()  < first_half["Low"].mean():
            ema_bear += 2

    total = ema_bull + ema_bear
    if total == 0:
        return {"direction": "sideways", "strength": 0}

    if ema_bull > ema_bear:
        strength = round((ema_bull / total) * 100)
        direction = "bullish" if strength > 55 else "sideways"
    elif ema_bear > ema_bull:
        strength = round((ema_bear / total) * 100)
        direction = "bearish" if strength > 55 else "sideways"
    else:
        return {"direction": "sideways", "strength": 50}

    return {"direction": direction, "strength": strength}


def detect_multi_timeframe_trend(daily_df: pd.DataFrame,
                                  h4_df: pd.DataFrame,
                                  h1_df: pd.DataFrame,
                                  m15_df: pd.DataFrame = None) -> dict:
    """Assess trend on D1, H4, H1, M15 for confluence."""
    results = {}
    frames = [("daily", daily_df), ("h4", h4_df), ("h1", h1_df)]
    if m15_df is not None and not (m15_df is None or (hasattr(m15_df, 'empty') and m15_df.empty)):
        frames.append(("m15", m15_df))

    for name, df in frames:
        enriched = add_all_indicators(df) if df is not None and not df.empty else df
        results[name] = detect_trend(enriched)

    # Overall bias — require majority alignment
    directions = [r["direction"] for r in results.values() if r["direction"] != "unknown"]
    bull_count  = directions.count("bullish")
    bear_count  = directions.count("bearish")
    total_tfs   = len(directions)

    # Need at least half+1 to be bullish/bearish for overall signal
    if bull_count >= max(2, (total_tfs + 1) // 2):
        overall = "bullish"
    elif bear_count >= max(2, (total_tfs + 1) // 2):
        overall = "bearish"
    else:
        overall = "mixed"

    results["overall"] = overall
    return results


# ─────────────────────────────────────────────
# CANDLESTICK PATTERNS
# ─────────────────────────────────────────────

def detect_candle_patterns(df: pd.DataFrame, lookback: int = 3) -> list:
    """
    Detect key reversal/continuation candlestick patterns.
    Returns list of detected pattern names.
    """
    if df is None or len(df) < 4:
        return []

    patterns = []
    recent = df.tail(lookback + 1)
    c = recent.iloc[-1]   # current candle
    p = recent.iloc[-2]   # previous candle

    body_c = abs(c["Close"] - c["Open"])
    range_c = c["High"] - c["Low"]
    body_p = abs(p["Close"] - p["Open"])
    range_p = p["High"] - p["Low"]

    upper_wick_c = c["High"] - max(c["Close"], c["Open"])
    lower_wick_c = min(c["Close"], c["Open"]) - c["Low"]

    # Doji
    if range_c > 0 and body_c / range_c < 0.1:
        patterns.append("Doji (indecision)")

    # Hammer (bullish reversal)
    if (lower_wick_c > body_c * 2 and
        upper_wick_c < body_c * 0.5 and
        c["Close"] > c["Open"]):
        patterns.append("Hammer (bullish reversal)")

    # Shooting Star (bearish reversal)
    if (upper_wick_c > body_c * 2 and
        lower_wick_c < body_c * 0.5 and
        c["Close"] < c["Open"]):
        patterns.append("Shooting Star (bearish reversal)")

    # Bullish Engulfing
    if (c["Close"] > c["Open"] and
        p["Close"] < p["Open"] and
        c["Open"] < p["Close"] and
        c["Close"] > p["Open"]):
        patterns.append("Bullish Engulfing")

    # Bearish Engulfing
    if (c["Close"] < c["Open"] and
        p["Close"] > p["Open"] and
        c["Open"] > p["Close"] and
        c["Close"] < p["Open"]):
        patterns.append("Bearish Engulfing")

    # Pinbar (long wick, small body)
    if range_c > 0:
        if lower_wick_c / range_c > 0.6:
            patterns.append("Bullish Pinbar")
        if upper_wick_c / range_c > 0.6:
            patterns.append("Bearish Pinbar")

    # Inside Bar (consolidation / breakout setup)
    if (c["High"] < p["High"] and c["Low"] > p["Low"]):
        patterns.append("Inside Bar (consolidation)")

    return patterns


# ─────────────────────────────────────────────
# SIGNAL SCORING FROM INDICATORS
# ─────────────────────────────────────────────

def score_indicators(df: pd.DataFrame) -> dict:
    """
    Produce a buy/sell score from all indicators on latest candle.
    Score: positive = bullish bias, negative = bearish bias.
    Each indicator contributes -2 to +2 points.
    """
    if df is None or df.empty:
        return {"score": 0, "signals": [], "total_weight": 0}

    # اگر اندیکاتورها قبلاً محاسبه شدن (EMA_21 موجوده) دوباره حساب نکن
    if "EMA_21" not in df.columns:
        df = add_all_indicators(df)
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    score   = 0
    signals = []

    # ── RSI ──
    rsi = last.get("RSI")
    if pd.notna(rsi):
        if rsi < 30:
            score += 2; signals.append(f"RSI oversold ({rsi:.1f}) → BUY")
        elif rsi < 40:
            score += 1; signals.append(f"RSI low ({rsi:.1f}) → mild BUY")
        elif rsi > 70:
            score -= 2; signals.append(f"RSI overbought ({rsi:.1f}) → SELL")
        elif rsi > 60:
            score -= 1; signals.append(f"RSI high ({rsi:.1f}) → mild SELL")
        else:
            signals.append(f"RSI neutral ({rsi:.1f})")

    # ── MACD ──
    macd_h = last.get("MACD_Hist")
    prev_h = prev.get("MACD_Hist")
    macd_v = last.get("MACD")
    sig_v  = last.get("MACD_Signal")
    if pd.notna(macd_h) and pd.notna(prev_h):
        if macd_h > 0 and prev_h <= 0:
            score += 2; signals.append("MACD bullish crossover → BUY")
        elif macd_h < 0 and prev_h >= 0:
            score -= 2; signals.append("MACD bearish crossover → SELL")
        elif macd_h > 0:
            score += 1; signals.append(f"MACD above zero (hist={macd_h:.2f}) → bullish")
        elif macd_h < 0:
            score -= 1; signals.append(f"MACD below zero (hist={macd_h:.2f}) → bearish")

    # ── EMA Cross & Alignment ──
    ema9  = last.get("EMA_9")
    ema21 = last.get("EMA_21")
    ema50 = last.get("EMA_50")
    ema200= last.get("EMA_200")
    price = last["Close"]

    if pd.notna(ema9) and pd.notna(ema21):
        prev_ema9  = prev.get("EMA_9")
        prev_ema21 = prev.get("EMA_21")
        if pd.notna(prev_ema9) and pd.notna(prev_ema21):
            if ema9 > ema21 and prev_ema9 <= prev_ema21:
                score += 2; signals.append("EMA 9 crossed above 21 → BUY")
            elif ema9 < ema21 and prev_ema9 >= prev_ema21:
                score -= 2; signals.append("EMA 9 crossed below 21 → SELL")

    if pd.notna(ema50) and pd.notna(ema200):
        if price > ema200:
            score += 1; signals.append(f"Price above EMA200 ({ema200:.1f}) → bullish")
        else:
            score -= 1; signals.append(f"Price below EMA200 ({ema200:.1f}) → bearish")

    # ── Bollinger Bands ──
    bb_pct = last.get("BB_Pct")
    bb_w   = last.get("BB_Width")
    if pd.notna(bb_pct):
        if bb_pct < 0.05:
            score += 2; signals.append(f"Price at BB lower band → potential BUY bounce")
        elif bb_pct > 0.95:
            score -= 2; signals.append(f"Price at BB upper band → potential SELL")
        elif bb_pct < 0.2:
            score += 1; signals.append(f"Price near BB lower band ({bb_pct:.2f})")
        elif bb_pct > 0.8:
            score -= 1; signals.append(f"Price near BB upper band ({bb_pct:.2f})")

    # ── Stochastic ──
    stoch_k = last.get("Stoch_K")
    stoch_d = last.get("Stoch_D")
    if pd.notna(stoch_k) and pd.notna(stoch_d):
        if stoch_k < 20 and stoch_d < 20:
            score += 2; signals.append(f"Stochastic oversold (K={stoch_k:.1f}) → BUY")
        elif stoch_k > 80 and stoch_d > 80:
            score -= 2; signals.append(f"Stochastic overbought (K={stoch_k:.1f}) → SELL")
        elif stoch_k > stoch_d and stoch_k < 50:
            score += 1; signals.append("Stoch bullish cross in low zone")
        elif stoch_k < stoch_d and stoch_k > 50:
            score -= 1; signals.append("Stoch bearish cross in high zone")

    return {
        "score":        score,
        "signals":      signals,
        "total_weight": 10,   # max absolute score
        "bias":         "bullish" if score > 0 else ("bearish" if score < 0 else "neutral")
    }


# ─────────────────────────────────────────────
# FULL TECHNICAL ANALYSIS REPORT
# ─────────────────────────────────────────────

def full_technical_report(snapshot: dict) -> dict:
    """
    Generate a complete technical analysis report from a market snapshot.
    Returns structured dict with all TA findings.
    """
    gold_1h    = snapshot.get("gold_1h",    pd.DataFrame())
    gold_4h    = snapshot.get("gold_4h",    pd.DataFrame())
    gold_daily = snapshot.get("gold_daily", pd.DataFrame())
    gold_15m   = snapshot.get("gold_15m",   pd.DataFrame())

    # Add indicators to all timeframes
    g1h  = add_all_indicators(gold_1h)
    g4h  = add_all_indicators(gold_4h)
    gd   = add_all_indicators(gold_daily)
    g15m = add_all_indicators(gold_15m)

    # Score each timeframe
    score_1h  = score_indicators(g1h)
    score_4h  = score_indicators(g4h)
    score_d   = score_indicators(gd)
    score_15m = score_indicators(g15m)

    # Multi-TF trend (now includes M15)
    mtf_trend = detect_multi_timeframe_trend(gd, g4h, g1h, g15m)

    # Key levels
    key_levels = find_key_levels(gd, g1h)

    # Candle patterns on 1H (most actionable)
    patterns_1h  = detect_candle_patterns(g1h)
    patterns_15m = detect_candle_patterns(g15m)

    # ATR for position sizing (use 1H ATR and 15M ATR for scalping)
    atr = None
    if g1h is not None and not g1h.empty and "ATR" in g1h.columns:
        atr_val = g1h["ATR"].iloc[-1]
        atr = round(float(atr_val), 2) if pd.notna(atr_val) else None

    atr_15m = None
    if g15m is not None and not g15m.empty and "ATR" in g15m.columns:
        atr_15m_val = g15m["ATR"].iloc[-1]
        atr_15m = round(float(atr_15m_val), 2) if pd.notna(atr_15m_val) else None

    # Latest values snapshot
    latest = {}
    if g1h is not None and not g1h.empty:
        last_row = g1h.iloc[-1]
        for col in ["Close", "RSI", "MACD", "MACD_Signal", "MACD_Hist",
                    "EMA_9", "EMA_21", "EMA_50", "EMA_200",
                    "BB_Upper", "BB_Middle", "BB_Lower",
                    "Stoch_K", "Stoch_D", "ATR"]:
            val = last_row.get(col)
            latest[col] = round(float(val), 2) if pd.notna(val) else None

    return {
        "latest_values":  latest,
        "atr_1h":         atr,
        "atr_15m":        atr_15m,
        "scores": {
            "daily":  score_d,
            "h4":     score_4h,
            "h1":     score_1h,
            "m15":    score_15m,
        },
        "mtf_trend":      mtf_trend,
        "key_levels":     key_levels,
        "patterns": {
            "h1":  patterns_1h,
            "m15": patterns_15m,
        }
    }
