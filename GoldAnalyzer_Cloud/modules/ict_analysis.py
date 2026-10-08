import pandas as pd
import numpy as np
from datetime import datetime, time
import pytz

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean()

def detect_order_blocks(df, lookback=50):
    if df is None or len(df) < lookback: return []
    obs = []
    df = df.copy()
    if 'ATR' not in df.columns:
        df['ATR'] = calculate_atr(df, 14)
    
    for i in range(len(df) - lookback, len(df) - 3):
        # Bullish OB
        if df['Close'].iloc[i] < df['Open'].iloc[i]:
            move = df['Close'].iloc[i+3] - df['Close'].iloc[i]
            atr = df['ATR'].iloc[i]
            if not pd.isna(atr) and move > 2 * atr:
                obs.append({
                    "type": "bullish_ob",
                    "high": float(df['High'].iloc[i]),
                    "low": float(df['Low'].iloc[i]),
                    "index": i,
                    "strength": float(move / atr),
                    "mitigated": False
                })
        # Bearish OB
        if df['Close'].iloc[i] > df['Open'].iloc[i]:
            move = df['Close'].iloc[i] - df['Close'].iloc[i+3]
            atr = df['ATR'].iloc[i]
            if not pd.isna(atr) and move > 2 * atr:
                obs.append({
                    "type": "bearish_ob",
                    "high": float(df['High'].iloc[i]),
                    "low": float(df['Low'].iloc[i]),
                    "index": i,
                    "strength": float(move / atr),
                    "mitigated": False
                })
                
    for ob in obs:
        ob_high = ob['high']
        ob_low = ob['low']
        for j in range(ob['index'] + 4, len(df)):
            if ob['type'] == 'bullish_ob' and df['Low'].iloc[j] <= ob_high:
                ob['mitigated'] = True
                break
            if ob['type'] == 'bearish_ob' and df['High'].iloc[j] >= ob_low:
                ob['mitigated'] = True
                break
    return [ob for ob in obs if not ob['mitigated']]

def detect_fair_value_gaps(df, lookback=50):
    if df is None or len(df) < 3: return []
    fvgs = []
    start_idx = max(1, len(df) - lookback)
    for i in range(start_idx, len(df) - 1):
        if df['High'].iloc[i-1] < df['Low'].iloc[i+1]:
            fvgs.append({
                "type": "bullish_fvg",
                "high": float(df['Low'].iloc[i+1]),
                "low": float(df['High'].iloc[i-1]),
                "midpoint": float((df['Low'].iloc[i+1] + df['High'].iloc[i-1]) / 2),
                "filled": False,
                "index": i
            })
        if df['Low'].iloc[i-1] > df['High'].iloc[i+1]:
            fvgs.append({
                "type": "bearish_fvg",
                "high": float(df['Low'].iloc[i-1]),
                "low": float(df['High'].iloc[i+1]),
                "midpoint": float((df['Low'].iloc[i-1] + df['High'].iloc[i+1]) / 2),
                "filled": False,
                "index": i
            })
            
    for fvg in fvgs:
        for j in range(fvg['index'] + 2, len(df)):
            if fvg['type'] == 'bullish_fvg' and df['Low'].iloc[j] <= fvg['low']:
                fvg['filled'] = True
                break
            if fvg['type'] == 'bearish_fvg' and df['High'].iloc[j] >= fvg['high']:
                fvg['filled'] = True
                break
    return [f for f in fvgs if not f['filled']]

def get_swings(df, lookback=20):
    highs, lows = [], []
    for i in range(lookback, len(df) - lookback):
        is_high = all(df['High'].iloc[i] > df['High'].iloc[i-j] for j in range(1, lookback+1)) and \
                  all(df['High'].iloc[i] > df['High'].iloc[i+j] for j in range(1, lookback+1))
        is_low = all(df['Low'].iloc[i] < df['Low'].iloc[i-j] for j in range(1, lookback+1)) and \
                 all(df['Low'].iloc[i] < df['Low'].iloc[i+j] for j in range(1, lookback+1))
        if is_high: highs.append({"price": float(df['High'].iloc[i]), "index": i})
        if is_low: lows.append({"price": float(df['Low'].iloc[i]), "index": i})
    return highs, lows

def detect_liquidity_sweeps(df, swing_lookback=20, confirmation_candles=3):
    """
    تشخیص دقیق شکار نقدینگی (Liquidity Sweeps) بدون تکرار مضاعف.
    تنها سقف‌ها و کف‌های اخیر (حداکثر ۵ کندل اخیر) که برای اولین بار هانت شده‌اند لحاظ می‌شوند.
    """
    if df is None or len(df) < swing_lookback * 2: return []
    highs, lows = get_swings(df, swing_lookback)
    
    sweeps = []
    swept_low_levels = set()
    swept_high_levels = set()
    
    # فقط کندل‌های تازه (حداکثر ۵ کندل اخیر) برای تاییدیه اسکلپ معتبر هستند
    recent_range = min(5, len(df))
    for i in range(len(df) - recent_range, len(df)):
        # بررسی شکار نقدینگی فروشندگان (Bullish Sweep - نفوذ به زیر کف و بازگشت به بالا)
        for low in lows:
            lvl = round(low['price'], 2)
            if lvl not in swept_low_levels and df['Low'].iloc[i] < low['price'] and df['Close'].iloc[i] > low['price']:
                swept_low_levels.add(lvl)
                sweeps.append({
                    "type": "bullish_sweep",
                    "swept_level": low['price'],
                    "sweep_candle_idx": i,
                    "reversal_confirmed": True
                })
                break
        
        # بررسی شکار نقدینگی خریداران (Bearish Sweep - نفوذ به بالای سقف و بازگشت به پایین)
        for high in highs:
            lvl = round(high['price'], 2)
            if lvl not in swept_high_levels and df['High'].iloc[i] > high['price'] and df['Close'].iloc[i] < high['price']:
                swept_high_levels.add(lvl)
                sweeps.append({
                    "type": "bearish_sweep",
                    "swept_level": high['price'],
                    "sweep_candle_idx": i,
                    "reversal_confirmed": True
                })
                break

    # حداکثر یک سویپ صعودی و یک سویپ نزولی تازه نگه داشته شود
    bullish = [s for s in sweeps if s['type'] == 'bullish_sweep']
    bearish = [s for s in sweeps if s['type'] == 'bearish_sweep']
    result = []
    if bullish: result.append(bullish[-1])
    if bearish: result.append(bearish[-1])
    return result

def detect_breaker_blocks(df, lookback=50):
    return []

def find_ote_zone(df, swing_lookback=30):
    if df is None or len(df) < swing_lookback * 2: return {}
    highs, lows = get_swings(df, swing_lookback)
    if not highs or not lows: return {}
    
    last_high = highs[-1]
    last_low = lows[-1]
    current_price = df['Close'].iloc[-1]
    
    direction = "bullish" if last_low['index'] < last_high['index'] else "bearish"
    swing_range = abs(last_high['price'] - last_low['price'])
    
    if direction == "bullish":
        ote_upper = last_high['price'] - swing_range * 0.618
        ote_lower = last_high['price'] - swing_range * 0.786
    else:
        ote_upper = last_low['price'] + swing_range * 0.786
        ote_lower = last_low['price'] + swing_range * 0.618
        
    price_in_ote = bool(ote_lower <= current_price <= ote_upper)
    return {
        "direction": str(direction),
        "swing_high": float(last_high['price']),
        "swing_low": float(last_low['price']),
        "ote_upper": float(ote_upper),
        "ote_lower": float(ote_lower),
        "price_in_ote": price_in_ote
    }

def detect_market_structure(df, lookback=30):
    if df is None or len(df) < lookback: return {"trend": "ranging", "last_event": None, "event_price": 0}
    highs, lows = get_swings(df, max(5, lookback // 3))
    
    if len(highs) >= 3 and len(lows) >= 3:
        # Failure Swing (SMS) detection
        # Bullish SMS: Uptrend fails to make higher high, breaks last low
        if highs[-2]['price'] > highs[-3]['price'] and highs[-1]['price'] <= highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
            return {"trend": "bearish", "last_event": "SMS", "event_price": lows[-1]['price']}
        # Bearish SMS: Downtrend fails to make lower low, breaks last high
        if lows[-2]['price'] < lows[-3]['price'] and lows[-1]['price'] >= lows[-2]['price'] and highs[-1]['price'] > highs[-2]['price']:
            return {"trend": "bullish", "last_event": "SMS", "event_price": highs[-1]['price']}
            
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
            return {"trend": "bullish", "last_event": "BOS", "event_price": highs[-1]['price']}
        elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
            return {"trend": "bearish", "last_event": "BOS", "event_price": lows[-1]['price']}
    return {"trend": "ranging", "last_event": None, "event_price": 0}

def get_premium_discount_zone(df, lookback=50):
    if df is None or len(df) < lookback: return {}
    recent_df = df.iloc[-lookback:]
    range_high = recent_df['High'].max()
    range_low = recent_df['Low'].min()
    if range_high == range_low: return {}
    
    equilibrium = (range_high + range_low) / 2
    current_price = df['Close'].iloc[-1]
    
    current_pct = (current_price - range_low) / (range_high - range_low)
    if current_price > equilibrium:
        zone = "premium"
    elif current_price < equilibrium:
        zone = "discount"
    else:
        zone = "equilibrium"
        
    return {
        "zone": zone,
        "range_high": float(range_high),
        "range_low": float(range_low),
        "equilibrium": float(equilibrium),
        "current_pct": float(current_pct)
    }

def detect_amd(df):
    """
    Detects Accumulation, Manipulation, Distribution (AMD) Profile.
    """
    if df is None or len(df) < 24: return {} 
    
    recent_df = df.iloc[-30:]
    range_high = recent_df['High'].max()
    range_low = recent_df['Low'].min()
    current_price = df['Close'].iloc[-1]
    
    if current_price < range_low + (range_high - range_low)*0.2 and df['Close'].iloc[-1] > df['Open'].iloc[-1]:
        return {"phase": "Manipulation", "direction": "bullish", "desc": "Turtle Soup Buy / Bearish Manipulation"}
    if current_price > range_high - (range_high - range_low)*0.2 and df['Close'].iloc[-1] < df['Open'].iloc[-1]:
        return {"phase": "Manipulation", "direction": "bearish", "desc": "Turtle Soup Sell / Bullish Manipulation"}
        
    return {"phase": "Accumulation/Distribution", "direction": "neutral", "desc": "Consolidation or Distribution"}

def detect_sh_bms_rto(df, liquidity_sweeps, market_structure, order_blocks):
    """
    Stop Hunt (SH) + Break in Market Structure (BMS) + Return to Order Block (RTO).
    """
    signals = []
    if not liquidity_sweeps or market_structure.get("last_event") is None:
        return signals
        
    last_sweep = liquidity_sweeps[-1]
    trend = market_structure.get("trend")
    last_event = market_structure.get("last_event")
    current_price = df['Close'].iloc[-1]
    
    if last_sweep['type'] == 'bullish_sweep' and trend == 'bullish' and last_event in ['BOS', 'SMS']:
        for ob in order_blocks:
            if ob['type'] == 'bullish_ob' and ob['low'] <= current_price <= ob['high'] * 1.002:
                signals.append("SH + BMS + RTO (Bullish Active)")
                break
                
    if last_sweep['type'] == 'bearish_sweep' and trend == 'bearish' and last_event in ['BOS', 'SMS']:
        for ob in order_blocks:
            if ob['type'] == 'bearish_ob' and ob['low'] * 0.998 <= current_price <= ob['high']:
                signals.append("SH + BMS + RTO (Bearish Active)")
                break
                
    return signals

def detect_institutional_levels(current_price: float) -> dict:
    """
    سطوح قیمتی نهادی (Institutional Key Levels) بر اساس کدهای رسمی اندیکاتورهای:
    - ICT Big Figure Mid Figure.mq4
    - ICT 80_20.mq4
    شامل:
    - Big Figure: مضارب 10 دلار (00)
    - Mid Figure: مضارب 5 دلار (50)
    - Institutional Sweet Spots: سطوح 20 و 80
    - Micro Cents: .00, .20, .50, .80
    """
    if not current_price or current_price <= 0:
        return {}
        
    base_int = int(current_price)
    
    # سطوح 10 دلاری (Big Figure)
    bf_lower = (base_int // 10) * 10
    bf_upper = bf_lower + 10
    mid_fig = bf_lower + 5.0
    level_20 = bf_lower + 2.0
    level_80 = bf_lower + 8.0
    
    # سطوح اعشاری (Cent Levels)
    cents_00 = float(base_int)
    cents_20 = float(base_int) + 0.20
    cents_50 = float(base_int) + 0.50
    cents_80 = float(base_int) + 0.80
    cents_00_next = float(base_int) + 1.00
    
    all_levels = [
        {"name": f"Big Figure (${bf_lower})", "price": float(bf_lower), "weight": 2.0},
        {"name": f"Big Figure (${bf_upper})", "price": float(bf_upper), "weight": 2.0},
        {"name": f"Mid Figure (${mid_fig})", "price": float(mid_fig), "weight": 1.5},
        {"name": f"Inst Level 20 (${level_20})", "price": float(level_20), "weight": 1.5},
        {"name": f"Inst Level 80 (${level_80})", "price": float(level_80), "weight": 1.5},
        {"name": "Micro Cent .00", "price": round(cents_00, 2), "weight": 1.0},
        {"name": "Micro Cent .20", "price": round(cents_20, 2), "weight": 1.0},
        {"name": "Micro Cent .50", "price": round(cents_50, 2), "weight": 1.0},
        {"name": "Micro Cent .80", "price": round(cents_80, 2), "weight": 1.0},
        {"name": "Micro Cent .00", "price": round(cents_00_next, 2), "weight": 1.0},
    ]
    
    all_levels.sort(key=lambda x: abs(x["price"] - current_price))
    nearest = all_levels[0]
    dist = float(abs(current_price - nearest["price"]))
    is_at_level = bool(dist <= 1.25) # درون ۱.۲۵ دلار
    
    return {
        "current_price": round(float(current_price), 2),
        "nearest_level_name": str(nearest["name"]),
        "nearest_level_price": float(nearest["price"]),
        "distance": round(dist, 2),
        "is_at_institutional_level": is_at_level,
        "big_figure_below": int(bf_lower),
        "big_figure_above": int(bf_upper),
        "mid_figure": float(mid_fig),
        "inst_20": float(level_20),
        "inst_80": float(level_80)
    }

def calculate_adr_metrics(df_daily: pd.DataFrame, current_price: float) -> dict:
    """
    محاسبه شاخص میانگین دامنه نوسان روزانه (ADR) برگرفته از ICT_ADR.mq4
    بررسی تکمیل ظرفیت حرکت روزانه و هشدار خستگی روند
    """
    if df_daily is None or len(df_daily) < 6:
        return {}
        
    past_days = df_daily.iloc[-6:-1]
    ranges = past_days['High'] - past_days['Low']
    adr_5 = float(ranges.tail(5).mean())
    adr_20 = float((df_daily['High'] - df_daily['Low']).tail(21).iloc[:-1].mean()) if len(df_daily) >= 22 else adr_5
    
    today_candle = df_daily.iloc[-1]
    today_high = float(today_candle['High'])
    today_low = float(today_candle['Low'])
    today_range = float(today_high - today_low)
    
    pct_used = round((today_range / adr_5) * 100, 1) if adr_5 > 0 else 0
    is_exhausted = pct_used >= 90.0
    
    return {
        "adr_5": round(adr_5, 2),
        "adr_20": round(adr_20, 2),
        "today_range": round(today_range, 2),
        "pct_used": pct_used,
        "is_exhausted": is_exhausted,
        "expected_high": round(today_low + adr_5, 2),
        "expected_low": round(today_high - adr_5, 2)
    }

def detect_draw_on_liquidity(df_daily: pd.DataFrame, df_4h: pd.DataFrame, current_price: float) -> dict:
    """
    تعیین جهت کشش نقدینگی (Draw on Liquidity - DOL) بر اساس قسمت دوم منتورشیپ ۲۰۲۲
    بازار به سمت Daily BSL، Daily SSL یا FVG های روزانه کشیده می‌شود.
    """
    if df_daily is None or len(df_daily) < 10:
        return {"bias": "neutral", "target_type": None, "target_price": None, "desc": "داده تایم روزانه برای DOL ناکافی"}
        
    recent_daily = df_daily.iloc[-20:]
    daily_highs = recent_daily['High'].values
    daily_lows = recent_daily['Low'].values
    
    bsl_targets = [float(h) for h in daily_highs if h > current_price + 2.0]
    ssl_targets = [float(l) for l in daily_lows if l < current_price - 2.0]
    
    nearest_bsl = min(bsl_targets) if bsl_targets else None
    nearest_ssl = max(ssl_targets) if ssl_targets else None
    
    ma_20 = recent_daily['Close'].mean()
    last_close = recent_daily['Close'].iloc[-1]
    
    if last_close > ma_20 and nearest_bsl:
        bias = "bullish"
        target_price = nearest_bsl
        target_type = "Daily BSL (استخر نقدینگی سقف روزانه)"
        desc = f"کشش قیمت به سمت استخر نقدینگی سقف روزانه ${nearest_bsl:.2f}"
    elif last_close < ma_20 and nearest_ssl:
        bias = "bearish"
        target_price = nearest_ssl
        target_type = "Daily SSL (استخر نقدینگی کف روزانه)"
        desc = f"کشش قیمت به سمت استخر نقدینگی کف روزانه ${nearest_ssl:.2f}"
    else:
        bias = "neutral"
        target_price = nearest_bsl or nearest_ssl
        target_type = "Equilibrium"
        desc = "تعادل نقدینگی در تایم‌فریم روزانه"
        
    return {
        "bias": bias,
        "target_type": target_type,
        "target_price": round(target_price, 2) if target_price else None,
        "desc": desc,
        "nearest_bsl": round(nearest_bsl, 2) if nearest_bsl else None,
        "nearest_ssl": round(nearest_ssl, 2) if nearest_ssl else None
    }

def detect_ict_2022_model(df, liquidity_sweeps, market_structure, fvgs, dol, current_price, kill_zone):
    """
    تشخیص ستاپ رسمی ICT 2022 Mentorship (قسمت اول تا سوم):
    1. شکار نقدینگی رنج خارجی (External Range Liquidity - ERL Run)
    2. تغییر یا شیفت ساختار بازار (Market Structure Shift - MSS) با مومنتوم بالا
    3. تشکیل گپ ارزش منصفانه ناشی از دیسپلیسمنت (Displacement FVG)
    4. بازگشت قیمت به نقدینگی رنج داخلی (Internal Range Liquidity - IRL Entry)
    5. هم‌راستایی با جهت کشش نقدینگی در تایم بالا (Draw on Liquidity - DOL)
    """
    if not liquidity_sweeps or not fvgs or market_structure.get("trend") == "ranging":
        return {"active": False, "setup_name": None}

    last_sweep = liquidity_sweeps[-1]
    trend = market_structure.get("trend")
    last_event = market_structure.get("last_event")
    
    # 1. تاییدیه ستاپ خرید (Bullish 2022 Mentorship Model)
    if last_sweep['type'] == 'bullish_sweep' and trend == 'bullish' and last_event in ['BOS', 'SMS']:
        for fvg in fvgs:
            if fvg['type'] == 'bullish_fvg' and fvg['low'] <= current_price <= fvg['high'] * 1.002:
                return {
                    "active": True,
                    "direction": "BUY",
                    "setup_name": "ICT 2022 Mentorship Model (Bullish)",
                    "entry_fvg": fvg,
                    "swept_level": last_sweep['swept_level'],
                    "dol_target": dol.get("target_price"),
                    "dol_type": dol.get("target_type"),
                    "in_killzone": kill_zone.get("in_kill_zone", False),
                    "confidence_boost": 4.5,
                    "desc": "شکار نقدینگی کف (SSL) + شیفت ساختار (MSS) + ورود در FVG رنج داخلی"
                }

    # 2. تاییدیه ستاپ فروش (Bearish 2022 Mentorship Model)
    if last_sweep['type'] == 'bearish_sweep' and trend == 'bearish' and last_event in ['BOS', 'SMS']:
        for fvg in fvgs:
            if fvg['type'] == 'bearish_fvg' and fvg['low'] * 0.998 <= current_price <= fvg['high']:
                return {
                    "active": True,
                    "direction": "SELL",
                    "setup_name": "ICT 2022 Mentorship Model (Bearish)",
                    "entry_fvg": fvg,
                    "swept_level": last_sweep['swept_level'],
                    "dol_target": dol.get("target_price"),
                    "dol_type": dol.get("target_type"),
                    "in_killzone": kill_zone.get("in_kill_zone", False),
                    "confidence_boost": 4.5,
                    "desc": "شکار نقدینگی سقف (BSL) + شیفت ساختار (MSS) + ورود در FVG رنج داخلی"
                }

    return {"active": False, "setup_name": None}

def is_kill_zone(utc_time=None):
    """
    زمان‌بندی دقیق کیل‌زون‌ها بر اساس قسمت سوم منتورشیپ ۲۰۲۲ و اندیکاتور Kill_Zones.mq4
    - London Open: 07:00 الی 10:00 UTC (ساعت 2 تا 5 صبح به وقت نیویورک)
    - NY Open (Morning): 12:30 الی 15:30 UTC (ساعت 8:30 تا 11 صبح به وقت نیویورک) با اوج نوسان در 09:30 NY Equity Open
    - NY Lunch: 16:30 الی 17:30 UTC (ساعت 12 تا 1 بعد از ظهر نیویورک — منطقه پرخطر و رِنج)
    - NY PM: 18:30 الی 20:30 UTC (ساعت 1:30 تا 3:30 بعد از ظهر نیویورک)
    - London Close: 15:00 الی 16:30 UTC
    """
    if utc_time is None:
        utc_time = datetime.now(pytz.UTC)
    elif not utc_time.tzinfo:
        utc_time = pytz.UTC.localize(utc_time)
        
    hour = utc_time.hour
    minute = utc_time.minute
    time_float = hour + minute / 60.0
    
    if 7.0 <= time_float < 10.0:
        return {"in_kill_zone": True, "kill_zone_name": "London Open (02:00-05:00 NY)", "quality": 1.0, "is_lunch": False}
    elif 12.5 <= time_float < 15.5:
        is_equity_open = 13.5 <= time_float <= 14.5
        name = "NY Open Morning (Equity Open 09:30 NY)" if is_equity_open else "NY Open Morning (08:30-11:00 NY)"
        return {"in_kill_zone": True, "kill_zone_name": name, "quality": 1.0, "is_lunch": False}
    elif 15.5 <= time_float < 16.5:
        return {"in_kill_zone": True, "kill_zone_name": "London Close (10:00-11:00 NY)", "quality": 0.8, "is_lunch": False}
    elif 16.5 <= time_float < 17.5:
        return {"in_kill_zone": False, "kill_zone_name": "NY Lunch Danger Zone (12:00-13:00 NY)", "quality": 0.1, "is_lunch": True}
    elif 18.0 <= time_float < 20.5:
        return {"in_kill_zone": True, "kill_zone_name": "NY Afternoon (13:30-16:00 NY)", "quality": 0.85, "is_lunch": False}
        
    return {"in_kill_zone": False, "kill_zone_name": "None", "quality": 0.0, "is_lunch": False}

def find_liquidity_pools(df, lookback=50):
    if df is None or len(df) < lookback: return {"buy_side_liquidity": [], "sell_side_liquidity": []}
    highs, lows = get_swings(df, 10)
    return {
        "buy_side_liquidity": sorted([h['price'] for h in highs]),
        "sell_side_liquidity": sorted([l['price'] for l in lows])
    }

def full_ict_report(df_1h, df_15m, df_4h=None, df_daily=None, utc_time=None):
    df_base = df_15m if df_15m is not None and not df_15m.empty else df_1h
    if df_base is None or df_base.empty:
        return {"ict_score": 0, "confirmation_count": 0}
        
    current_price = df_base['Close'].iloc[-1]
    
    order_blocks = detect_order_blocks(df_base, 50)
    fvgs = detect_fair_value_gaps(df_base, 50)
    liquidity_sweeps = detect_liquidity_sweeps(df_base, 20, 3)
    ote_zone = find_ote_zone(df_base, 30)
    market_structure = detect_market_structure(df_base, 30)
    premium_discount = get_premium_discount_zone(df_base, 50)
    kill_zone = is_kill_zone(utc_time)
    liquidity_pools = find_liquidity_pools(df_base, 50)
    amd_profile = detect_amd(df_base)
    setup_signals = detect_sh_bms_rto(df_base, liquidity_sweeps, market_structure, order_blocks)
    
    # ── مفاهیم پیشرفته منتورشیپ ۲۰۲۲ و اندیکاتورهای سازمانی ──
    institutional_levels = detect_institutional_levels(current_price)
    adr_metrics = calculate_adr_metrics(df_daily, current_price) if df_daily is not None else {}
    draw_on_liquidity = detect_draw_on_liquidity(df_daily, df_4h, current_price) if df_daily is not None else {}
    model_2022 = detect_ict_2022_model(df_base, liquidity_sweeps, market_structure, fvgs, draw_on_liquidity, current_price, kill_zone)
    
    ict_buy_score = 0.0
    ict_sell_score = 0.0
    confirmation_count = 0
    signals = []
    
    def add_sig(msg):
        if msg and msg not in signals:
            signals.append(msg)
    
    # ۱. ساختار بازار (BOS & SMS)
    if market_structure.get("trend") == "bullish":
        ict_buy_score += 2.0
        confirmation_count += 1
        add_sig("ساختار بازار صعودی (BOS)")
    elif market_structure.get("trend") == "bearish":
        ict_sell_score += 2.0
        confirmation_count += 1
        add_sig("ساختار بازار نزولی (BOS)")
        
    if market_structure.get("last_event") == "SMS":
        if market_structure.get("trend") == "bullish":
            ict_buy_score += 2.5
            confirmation_count += 1
            add_sig("تغییر ساختار به صعودی با شکست کف (Bullish SMS)")
        else:
            ict_sell_score += 2.5
            confirmation_count += 1
            add_sig("تغییر ساختار به نزولی با شکست سقف (Bearish SMS)")
        
    # ۲. شکار نقدینگی رنج خارجی (ERL Sweeps)
    for sweep in liquidity_sweeps:
        if sweep['type'] == 'bullish_sweep':
            ict_buy_score += 3.0
            confirmation_count += 1
            add_sig("شکار نقدینگی فروشندگان (Bullish Sweep)")
        elif sweep['type'] == 'bearish_sweep':
            ict_sell_score += 3.0
            confirmation_count += 1
            add_sig("شکار نقدینگی خریداران (Bearish Sweep)")
            
    # ۳. فاز AMD (سوپ لاک‌پشت / دستکاری نقدینگی)
    if amd_profile.get("phase") == "Manipulation":
        if amd_profile.get("direction") == "bullish":
            ict_buy_score += 2.0
            add_sig("دستکاری نزولی جهت شکار نقدینگی (Turtle Soup Buy)")
        elif amd_profile.get("direction") == "bearish":
            ict_sell_score += 2.0
            add_sig("دستکاری صعودی جهت شکار نقدینگی (Turtle Soup Sell)")
            
    # ۴. ستاپ ترکیبی SH + BMS + RTO
    for setup in setup_signals:
        if "Bullish" in setup:
            ict_buy_score += 4.0
            confirmation_count += 1
            add_sig("ستاپ قدرتمند SH + BMS + RTO صعودی")
        if "Bearish" in setup:
            ict_sell_score += 4.0
            confirmation_count += 1
            add_sig("ستاپ قدرتمند SH + BMS + RTO نزولی")
            
    # ۵. ستاپ رسمی ICT 2022 Mentorship Model (ورود در FVG پس از هانت ERL و شیفت MSS)
    if model_2022.get("active"):
        confirmation_count += 2
        if model_2022.get("direction") == "BUY":
            ict_buy_score += 4.5
            add_sig("💎 ستاپ رسمی ICT 2022 Mentorship صعودی (ورود FVG رنج داخلی پس از MSS)")
        elif model_2022.get("direction") == "SELL":
            ict_sell_score += 4.5
            add_sig("💎 ستاپ رسمی ICT 2022 Mentorship نزولی (ورود FVG رنج داخلی پس از MSS)")
            
    # ۶. هم‌راستایی با جهت کشش نقدینگی (Draw on Liquidity - DOL)
    if draw_on_liquidity.get("bias") == "bullish":
        ict_buy_score += 1.5
        add_sig(f"🎯 جهت کشش نقدینگی روزانه: صعودی ({draw_on_liquidity.get('desc')})")
    elif draw_on_liquidity.get("bias") == "bearish":
        ict_sell_score += 1.5
        add_sig(f"🎯 جهت کشش نقدینگی روزانه: نزولی ({draw_on_liquidity.get('desc')})")
        
    # ۷. سطوح نهادی (Big Figure 00 / Mid Figure 50 / Inst 80-20)
    if institutional_levels.get("is_at_institutional_level"):
        lvl_name = institutional_levels.get("nearest_level_name")
        lvl_price = institutional_levels.get("nearest_level_price")
        add_sig(f"🏦 تراز نقدینگی نهادی: {lvl_name} در قیمت ${lvl_price:.2f}")
        # ترازهای نهادی اعتبار ستاپ را تقویت می‌کنند
        ict_buy_score += 0.5
        ict_sell_score += 0.5
        
    # ۸. مناطق ارزان و گران (Premium / Discount)
    pd_zone = premium_discount.get("zone")
    if pd_zone == "discount":
        ict_buy_score += 2.5
        ict_sell_score -= 3.5  # جریمه سنگین برای فروش در منطقه تخفیف
        add_sig("قیمت در منطقه ارزان (Discount - مساعد خرید)")
    elif pd_zone == "premium":
        ict_sell_score += 2.5
        ict_buy_score -= 3.5   # جریمه سنگین برای خرید در منطقه گران
        add_sig("قیمت در منطقه گران (Premium - مساعد فروش)")
        
    # ۹. نقطه بهینه ورود (OTE 62%-79%)
    if ote_zone.get("price_in_ote"):
        if ote_zone.get("direction") == "bullish" and pd_zone != "premium":
            ict_buy_score += 2.0
            confirmation_count += 1
            add_sig("ورود بهینه صعودی (OTE)")
        elif ote_zone.get("direction") == "bearish" and pd_zone != "discount":
            ict_sell_score += 2.0
            confirmation_count += 1
            add_sig("ورود بهینه نزولی (OTE)")
            
    # ۱۰. واکنش به FVG
    for fvg in fvgs:
        if fvg['type'] == 'bullish_fvg' and fvg['low'] <= current_price <= fvg['high']:
            ict_buy_score += 1.5
            ict_sell_score -= 1.5
            confirmation_count += 1
            add_sig("واکنش حمایتی به FVG صعودی")
            break
        elif fvg['type'] == 'bearish_fvg' and fvg['low'] <= current_price <= fvg['high']:
            ict_sell_score += 1.5
            ict_buy_score -= 1.5
            confirmation_count += 1
            add_sig("واکنش مقاومتی به FVG نزولی")
            break
            
    # ۱۱. واکنش به Order Block
    for ob in order_blocks:
        if ob['type'] == 'bullish_ob' and ob['low'] - 1.0 <= current_price <= ob['high'] + 1.0:
            ict_buy_score += 2.0
            ict_sell_score -= 2.0
            confirmation_count += 1
            add_sig("واکنش به اوردر بلاک صعودی")
            break
        elif ob['type'] == 'bearish_ob' and ob['low'] - 1.0 <= current_price <= ob['high'] + 1.0:
            ict_sell_score += 2.0
            ict_buy_score -= 2.0
            confirmation_count += 1
            add_sig("واکنش به اوردر بلاک نزولی")
            break
            
    # ۱۲. اثر کیل‌زون و فیلتر زمان ناهار نیویورک
    if kill_zone.get("in_kill_zone"):
        ict_buy_score += 1.5
        ict_sell_score += 1.5
        add_sig(f"🕒 زمان‌بندی طلایی: فعال در {kill_zone.get('kill_zone_name')}")
    elif kill_zone.get("is_lunch"):
        ict_buy_score -= 2.5
        ict_sell_score -= 2.5
        add_sig("⚠️ هشدار سشن ناهار نیویورک: نقدینگی پایین و تله بازارساز")
    else:
        ict_buy_score -= 0.5
        ict_sell_score -= 0.5
        
    # ۱۳. فیلتر اشباع دامنه نوسان روزانه (ADR)
    if adr_metrics.get("is_exhausted"):
        # اگر بیش از ۹۰٪ دامنه روزانه پر شده، ورودهای جدید پرخطر هستند
        ict_buy_score -= 2.0
        ict_sell_score -= 2.0
        add_sig(f"⚠️ هشدار ADR: مصرف {adr_metrics.get('pct_used')}% دامنه نوسان روزانه — احتمال توقف یا بازگشت")
        
    raw_score = ict_buy_score - ict_sell_score
    ict_score = max(-10.0, min(10.0, round(raw_score, 1)))
    
    buy_sl = None
    sell_sl = None
    
    ssl = liquidity_pools.get("sell_side_liquidity", [])
    if ssl:
        below_price = [p for p in ssl if p < current_price]
        if below_price: buy_sl = max(below_price)
        
    bsl = liquidity_pools.get("buy_side_liquidity", [])
    if bsl:
        above_price = [p for p in bsl if p > current_price]
        if above_price: sell_sl = min(above_price)
        
    return {
        "ict_score": ict_score,
        "ict_buy_score": ict_buy_score,
        "ict_sell_score": ict_sell_score,
        "confirmation_count": confirmation_count,
        "signals": signals,
        "order_blocks": order_blocks,
        "fvgs": fvgs,
        "liquidity_sweeps": liquidity_sweeps,
        "ote_zone": ote_zone,
        "market_structure": market_structure,
        "premium_discount": premium_discount,
        "kill_zone": kill_zone,
        "liquidity_pools": liquidity_pools,
        "amd_profile": amd_profile,
        "setup_signals": setup_signals,
        "institutional_levels": institutional_levels,
        "adr_metrics": adr_metrics,
        "draw_on_liquidity": draw_on_liquidity,
        "model_2022": model_2022,
        "sl_recommendation": {"buy_sl": buy_sl, "sell_sl": sell_sl}
    }
