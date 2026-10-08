"""
Data Fetcher Module
-------------------
Fetches XAU/USD price data, DXY data, economic calendar events,
and financial news from various free sources.
"""

import yfinance as yf
import pandas as pd
import requests
import feedparser
from datetime import datetime, timedelta
import pytz
import json
import time
import pickle
import os
import concurrent.futures

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge")
_CACHE_FILE = os.path.join(_BRIDGE_DIR, "snapshot_cache.pkl")


def get_cached_snapshot() -> dict:
    """بارگذاری آخرین اسنپ‌شات ذخیره‌شده از دیسک جهت نمایش فوری محتوا"""
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, "rb") as f:
                data = pickle.load(f)
                if isinstance(data, dict) and "gold_1h" in data and not data["gold_1h"].empty:
                    return data
    except Exception as e:
        print(f"[DataFetcher] Cache read error: {e}")
    return {}


def save_snapshot_cache(snapshot: dict):
    """ذخیره اسنپ‌شات در دیسک جهت بارگذاری آنی در اجرای بعدی"""
    try:
        os.makedirs(_BRIDGE_DIR, exist_ok=True)
        with open(_CACHE_FILE, "wb") as f:
            pickle.dump(snapshot, f)
    except Exception as e:
        print(f"[DataFetcher] Cache write error: {e}")


# ─────────────────────────────────────────────
# PRICE DATA
# ─────────────────────────────────────────────

def fetch_gold_data(period: str = "60d", interval: str = "1h") -> pd.DataFrame:
    """
    Fetch XAU/USD OHLCV data via yfinance.
    
    period:   '1d','5d','7d','30d','60d','90d','1y'
    interval: '1m','5m','15m','30m','1h','4h','1d'
    """
    try:
        ticker = yf.Ticker("GC=F")          # Gold Futures (tracks XAU/USD closely)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            # fallback to spot gold ETF (GLD)
            ticker = yf.Ticker("GLD")
            df = ticker.history(period=period, interval=interval)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df
    except Exception as e:
        print(f"[DataFetcher] Error fetching gold data: {e}")
        return pd.DataFrame()


def fetch_gold_daily(days: int = 120) -> pd.DataFrame:
    """Fetch daily OHLCV for gold (used for higher-TF analysis)."""
    try:
        ticker = yf.Ticker("GC=F")
        df = ticker.history(period=f"{days}d", interval="1d")
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df
    except Exception as e:
        print(f"[DataFetcher] Error fetching daily gold: {e}")
        return pd.DataFrame()


def fetch_current_price() -> dict:
    """
    دریافت قیمت لحظه‌ای و واقعی طلا (XAU/USD).
    ترتیب بررسی منابع:
      ۱. API زنده Gold-API Spot
      ۲. GoldPrice.org Feed
      ۳. Paxos Gold (PAXG 1:1 Gold Spot با آپدیت میلی‌ثانیه‌ای)
      ۴. Yahoo Finance XAUUSD=X (Spot Forex)
      ۵. Yahoo Finance GC=F (COMEX Futures)
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    # منبع ۱: Gold-API Spot (بسیار دقیق و آنی)
    try:
        r = requests.get("https://api.gold-api.com/price/XAU", headers=headers, timeout=2.0)
        if r.status_code == 200:
            data = r.json()
            price = float(data.get("price", 0))
            if 1500 < price < 6000:
                return {
                    "price":     round(price, 2),
                    "timestamp": datetime.now(pytz.UTC).isoformat(),
                    "source":    "Gold-API Spot (Real-time)"
                }
    except Exception:
        pass

    # منبع ۲: Paxos Gold (بر پایه طلای فیزیکی ۱ به ۱ - ۲۴ ساعته بدون وقفه)
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", headers=headers, timeout=2.0)
        if r.status_code == 200:
            p = float(r.json().get("price", 0))
            if 1500 < p < 6000:
                return {
                    "price":     round(p, 2),
                    "timestamp": datetime.now(pytz.UTC).isoformat(),
                    "source":    "Gold Spot Feed (PAXG 24/7)"
                }
    except Exception:
        pass

    # منبع ۳: GoldPrice.org
    try:
        r = requests.get("https://data-asg.goldprice.org/dbXRates/USD", headers=headers, timeout=2.0)
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            if items:
                p = float(items[0].get("xauPrice", 0))
                if 1500 < p < 6000:
                    return {
                        "price":     round(p, 2),
                        "timestamp": datetime.now(pytz.UTC).isoformat(),
                        "source":    "GoldPrice.org"
                    }
    except Exception:
        pass

    # منبع ۴: Yahoo Finance GC=F (COMEX Gold)
    try:
        ticker = yf.Ticker("GC=F")
        info   = ticker.fast_info
        if hasattr(info, "last_price") and info.last_price:
            p = float(info.last_price)
            if 1500 < p < 6000:
                return {
                    "price":     round(p, 2),
                    "timestamp": datetime.now(pytz.UTC).isoformat(),
                    "source":    "yfinance GC=F"
                }
    except Exception:
        pass

    # منبع ۵: Yahoo Finance GC=F (Futures)
    try:
        ticker = yf.Ticker("GC=F")
        info   = ticker.fast_info
        price  = None
        if hasattr(info, "last_price") and info.last_price:
            price = float(info.last_price)
        elif hasattr(info, "previous_close"):
            price = float(info.previous_close)
        if price and 1500 < price < 6000:
            return {
                "price":     round(price, 2),
                "timestamp": datetime.now(pytz.UTC).isoformat(),
                "source":    "yfinance GC=F"
            }
    except Exception:
        pass

    return {"price": None, "timestamp": None, "source": "error"}


def fetch_live_price_fast() -> float | None:
    """
    فقط عدد قیمت لحظه‌ای — سریع‌ترین راه ممکن برای به‌روزرسانی هدر و نمودار.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # تست سریع Paxos Gold یا Gold-API (کمتر از ۱ ثانیه)
    for url, key, subkey in [
        ("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", "price", None),
        ("https://api.gold-api.com/price/XAU", "price", None),
    ]:
        try:
            r = requests.get(url, headers=headers, timeout=1.5)
            if r.status_code == 200:
                val = float(r.json().get(key, 0))
                if 1500 < val < 6000:
                    return round(val, 2)
        except Exception:
            pass

    # fallback سریع از yfinance
    try:
        t = yf.Ticker("GC=F")
        fi = t.fast_info
        if hasattr(fi, "last_price") and fi.last_price:
            p = float(fi.last_price)
            if 1500 < p < 6000:
                return round(p, 2)
    except Exception:
        pass

    return None



def fetch_dxy_data(period: str = "60d", interval: str = "1h") -> pd.DataFrame:
    """Fetch US Dollar Index (DXY) data — inverse correlation with gold."""
    try:
        ticker = yf.Ticker("DX-Y.NYB")
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            ticker = yf.Ticker("UUP")   # USD ETF as fallback
            df = ticker.history(period=period, interval=interval)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df
    except Exception as e:
        print(f"[DataFetcher] Error fetching DXY: {e}")
        return pd.DataFrame()


def fetch_us10y_yield() -> dict:
    """Fetch US 10-Year Treasury Yield (^TNX) — key fundamental for gold."""
    try:
        ticker = yf.Ticker("^TNX")
        hist = ticker.history(period="5d", interval="1d")
        if hist.empty:
            return {"yield": None, "change": None}
        last_yield = float(hist["Close"].iloc[-1])
        prev_yield = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last_yield
        return {
            "yield": round(last_yield, 3),
            "change": round(last_yield - prev_yield, 3),
            "timestamp": datetime.now(pytz.UTC).isoformat()
        }
    except Exception as e:
        print(f"[DataFetcher] Error fetching 10Y yield: {e}")
        return {"yield": None, "change": None}


def fetch_sp500_data(period: str = "30d", interval: str = "1d") -> pd.DataFrame:
    """Fetch S&P 500 data (risk-on/risk-off indicator)."""
    try:
        ticker = yf.Ticker("^GSPC")
        df = ticker.history(period=period, interval=interval)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception as e:
        print(f"[DataFetcher] Error fetching SP500: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# NEWS & ECONOMIC CALENDAR
# ─────────────────────────────────────────────

# High-impact keywords that move gold
GOLD_KEYWORDS = [
    "gold", "xau", "fed", "federal reserve", "powell", "inflation", "cpi",
    "pce", "nfp", "non-farm", "interest rate", "rate hike", "rate cut",
    "fomc", "treasury", "dollar", "dxy", "geopolit", "war", "sanction",
    "recession", "gdp", "unemployment", "jobs report", "debt ceiling",
    "safe haven", "risk off", "risk-off", "china", "russia", "ukraine",
    "middle east", "oil", "crude", "commodity"
]


def fetch_gold_news(max_items: int = 15) -> list:
    """
    Fetch latest gold/macro news using working feeds with strict request timeouts.
    """
    feeds = [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US",
        "https://finance.yahoo.com/rss/headline?s=GC=F",
        "https://www.marketwatch.com/rss/topstories",
        "https://www.investing.com/rss/news_285.rss"
    ]

    news_items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    def _fetch_single_feed(url):
        try:
            r = requests.get(url, headers=headers, timeout=2.0)
            if r.status_code == 200 and r.content:
                f = feedparser.parse(r.content)
                extracted = []
                for entry in f.entries[:6]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", entry.get("description", ""))
                    link = entry.get("link", "")
                    published = entry.get("published", entry.get("updated", ""))
                    combined = (title + " " + summary).lower()
                    if any(kw in combined for kw in GOLD_KEYWORDS):
                        extracted.append({
                            "title": title,
                            "summary": summary[:300],
                            "link": link,
                            "published": published,
                            "source": f.feed.get("title", url),
                            "relevance": _score_news_relevance(combined)
                        })
                return extracted
        except Exception:
            pass
        return []

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = pool.map(_fetch_single_feed, feeds, timeout=3.0)
            for r in results:
                if r:
                    news_items.extend(r)
    except Exception:
        pass

    news_items.sort(key=lambda x: x["relevance"], reverse=True)
    return news_items[:max_items]


def _score_news_relevance(text: str) -> int:
    """Score news relevance to gold trading (higher = more relevant)."""
    score = 0
    high_impact = ["fed", "fomc", "cpi", "nfp", "non-farm", "interest rate",
                   "rate hike", "rate cut", "pce", "inflation", "powell", "war",
                   "sanction", "geopolit", "debt ceiling"]
    medium_impact = ["gold", "xau", "dollar", "dxy", "treasury", "yield",
                     "recession", "gdp", "unemployment"]
    for kw in high_impact:
        if kw in text:
            score += 3
    for kw in medium_impact:
        if kw in text:
            score += 1
    return score


def fetch_economic_calendar() -> list:
    """
    Fetch upcoming high-impact economic events.
    Uses forexfactory-style scraping from investing.com economic calendar RSS.
    Falls back to known scheduled events when scraping fails.
    """
    events = []

    # Try fetching from ForexFactory RSS (publicly available)
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            for item in data:
                impact = item.get("impact", "").lower()
                if impact in ["high", "medium"]:
                    events.append({
                        "title": item.get("title", ""),
                        "country": item.get("country", ""),
                        "date": item.get("date", ""),
                        "time": item.get("time", ""),
                        "impact": impact,
                        "forecast": item.get("forecast", ""),
                        "previous": item.get("previous", ""),
                        "actual": item.get("actual", "")
                    })
    except Exception:
        pass

    # Only add fallback events if NO real events were fetched at all
    # (previously this was adding fake "high" events unconditionally,
    #  causing cal_risk="very_high" and blocking all signals)
    if len(events) == 0:
        events.extend(_get_known_events_this_week())

    return events


def _get_known_events_this_week() -> list:
    """
    Return minimal fallback context events — only used when live calendar fails entirely.
    These are marked 'medium' not 'high' to avoid blocking signals on fake data.
    """
    return [
        {
            "title": "Fed Watch / Macro Context",
            "country": "USD",
            "date": "ongoing",
            "time": "—",
            "impact": "medium",   # ← medium, NOT high (prevents fake very_high risk)
            "forecast": "N/A",
            "previous": "N/A",
            "actual": "Pending"
        }
    ]


# ─────────────────────────────────────────────
# SENTIMENT SCORING
# ─────────────────────────────────────────────

def analyze_news_sentiment(news_items: list) -> dict:
    """
    Simple keyword-based sentiment analysis for gold.
    Returns bullish/bearish/neutral sentiment with score.
    """
    bullish_keywords = [
        "rate cut", "dovish", "inflation rises", "inflation high", "safe haven",
        "geopolitical", "war", "conflict", "tension", "sanction", "recession",
        "crisis", "uncertainty", "risk off", "risk-off", "weak dollar",
        "dollar falls", "dollar weakens", "gold rises", "gold rally",
        "gold surges", "buying gold", "demand for gold", "debt crisis"
    ]
    bearish_keywords = [
        "rate hike", "hawkish", "strong dollar", "dollar rises", "dollar rallies",
        "gold falls", "gold drops", "gold declines", "sell gold", "risk on",
        "risk-on", "economic recovery", "strong jobs", "beat expectations",
        "higher yields", "treasury yields rise", "fed tightening"
    ]

    bull_score = 0
    bear_score = 0
    relevant_titles = []

    for item in news_items:
        text = (item["title"] + " " + item["summary"]).lower()
        for kw in bullish_keywords:
            if kw in text:
                bull_score += item.get("relevance", 1)
                break
        for kw in bearish_keywords:
            if kw in text:
                bear_score += item.get("relevance", 1)
                break
        if item.get("relevance", 0) >= 3:
            relevant_titles.append(item["title"])

    total = bull_score + bear_score
    if total == 0:
        sentiment = "neutral"
        confidence = 0
    elif bull_score > bear_score:
        sentiment = "bullish"
        confidence = round((bull_score / total) * 100)
    elif bear_score > bull_score:
        sentiment = "bearish"
        confidence = round((bear_score / total) * 100)
    else:
        sentiment = "neutral"
        confidence = 50

    return {
        "sentiment": sentiment,
        "bullish_score": bull_score,
        "bearish_score": bear_score,
        "confidence": confidence,
        "key_headlines": relevant_titles[:5]
    }


# ─────────────────────────────────────────────
# COMBINED DATA SNAPSHOT
# ─────────────────────────────────────────────

def get_full_market_snapshot() -> dict:
    """
    دریافت همزمان تمامی داده‌های بازار با اجرای موازی (Parallel ThreadPool)
    جهت رسیدن به بالاترین سرعت و جلوگیری از فریز شدن برنامه
    """
    print("[DataFetcher] Fetching market data in parallel...")
    start_t = time.time()
    snapshot = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        f_current  = executor.submit(fetch_current_price)
        f_g1h      = executor.submit(fetch_gold_data, "60d", "1h")
        f_g15m     = executor.submit(fetch_gold_data, "5d", "15m")
        f_gdaily   = executor.submit(fetch_gold_daily, 120)
        f_dxy      = executor.submit(fetch_dxy_data, "60d", "1h")
        f_us10y    = executor.submit(fetch_us10y_yield)
        f_sp500    = executor.submit(fetch_sp500_data, "30d", "1d")
        f_news     = executor.submit(fetch_gold_news, 15)
        f_cal      = executor.submit(fetch_economic_calendar)

        # دریافت نتایج با محافظت تایم‌اوت
        try:
            snapshot["current"] = f_current.result(timeout=4.0)
        except Exception:
            snapshot["current"] = None

        try:
            snapshot["gold_1h"] = f_g1h.result(timeout=6.0)
        except Exception:
            snapshot["gold_1h"] = pd.DataFrame()

        try:
            snapshot["gold_15m"] = f_g15m.result(timeout=6.0)
        except Exception:
            snapshot["gold_15m"] = pd.DataFrame()

        # اگر قیمت لحظه‌ای ناموفق بود، با بالاترین دقت از آخرین کندل زنده ۱۵ دقیقه یا ۱ ساعته استخراج کن
        if not snapshot.get("current") or not isinstance(snapshot["current"], dict) or snapshot["current"].get("price", 0) <= 0:
            p_live = 0.0
            if not snapshot.get("gold_15m", pd.DataFrame()).empty:
                p_live = float(snapshot["gold_15m"]["Close"].iloc[-1])
            elif not snapshot.get("gold_1h", pd.DataFrame()).empty:
                p_live = float(snapshot["gold_1h"]["Close"].iloc[-1])
            
            if p_live > 0:
                snapshot["current"] = {
                    "price": round(p_live, 2),
                    "source": "Live Candle (Real-time)",
                    "timestamp": datetime.now(pytz.UTC).isoformat()
                }
            else:
                snapshot["current"] = {"price": 4170.80, "source": "Fallback"}

        # اعتبارسنجی هماهنگی قیمت جاری با کندل‌های زنده طلا
        if snapshot.get("current") and not snapshot.get("gold_1h", pd.DataFrame()).empty:
            candle_price = float(snapshot["gold_1h"]["Close"].iloc[-1])
            curr_price = float(snapshot["current"].get("price", 0))
            if curr_price > 0 and candle_price > 0:
                if abs(curr_price - candle_price) / candle_price > 0.15:
                    snapshot["current"] = {
                        "price": round(candle_price, 2),
                        "source": "Live Candle Override",
                        "timestamp": datetime.now(pytz.UTC).isoformat()
                    }

        try:
            snapshot["gold_daily"] = f_gdaily.result(timeout=6.0)
        except Exception:
            snapshot["gold_daily"] = pd.DataFrame()

        try:
            snapshot["dxy"] = f_dxy.result(timeout=6.0)
        except Exception:
            snapshot["dxy"] = pd.DataFrame()

        try:
            snapshot["us10y"] = f_us10y.result(timeout=6.0)
        except Exception:
            snapshot["us10y"] = {"yield": None, "change": None}

        try:
            snapshot["sp500"] = f_sp500.result(timeout=6.0)
        except Exception:
            snapshot["sp500"] = pd.DataFrame()

        try:
            snapshot["news"] = f_news.result(timeout=4.0)
        except Exception:
            snapshot["news"] = []

        try:
            snapshot["calendar"] = f_cal.result(timeout=4.0)
        except Exception:
            snapshot["calendar"] = []

    # محاسبه تایم‌فریم ۴ ساعته از روی ۱ ساعته بدون درخواست مجدد اینترنت
    g1h = snapshot.get("gold_1h")
    if g1h is not None and not g1h.empty:
        try:
            snapshot["gold_4h"] = g1h.resample("4h").agg({
                "Open":   "first",
                "High":   "max",
                "Low":    "min",
                "Close":  "last",
                "Volume": "sum"
            }).dropna()
        except Exception:
            snapshot["gold_4h"] = pd.DataFrame()
    else:
        # اگر اینترنت قطع بود، از کش قدیمی برای داده‌های حجیم استفاده کن
        old_cache = get_cached_snapshot()
        if old_cache and not old_cache.get("gold_1h", pd.DataFrame()).empty:
            snapshot["gold_1h"] = old_cache["gold_1h"]
            snapshot["gold_4h"] = old_cache.get("gold_4h", pd.DataFrame())
            snapshot["gold_15m"] = old_cache.get("gold_15m", pd.DataFrame())
            snapshot["gold_daily"] = old_cache.get("gold_daily", pd.DataFrame())
            if snapshot.get("dxy", pd.DataFrame()).empty:
                snapshot["dxy"] = old_cache.get("dxy", pd.DataFrame())
        else:
            snapshot["gold_4h"] = pd.DataFrame()

    snapshot["sentiment"]  = analyze_news_sentiment(snapshot.get("news", []))
    snapshot["fetched_at"] = datetime.now(pytz.UTC).isoformat()

    # ذخیره در کش دیسک برای لود فوری برنامه در دفعات بعدی
    if snapshot.get("gold_1h") is not None and not snapshot["gold_1h"].empty:
        save_snapshot_cache(snapshot)

    print(f"[DataFetcher] Snapshot complete in {time.time() - start_t:.2f}s.")
    return snapshot
