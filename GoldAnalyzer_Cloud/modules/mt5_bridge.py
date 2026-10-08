"""
ماژول پل ارتباطی با متاتریدر ۵ (MetaTrader 5 Bridge)
---------------------------------------------------
امکان اتصال به متاتریدر ۵، تنظیمات حساب، ارسال سیگنال‌ها
و هماهنگی معاملات خودکار (Auto Trading / Scalping)
"""

import os
import json
import csv
from datetime import datetime, timezone

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BRIDGE_DIR = os.path.join(_DIR, "bridge")
_CONFIG_FILE = os.path.join(_BRIDGE_DIR, "mt5_config.json")
_LATEST_SIGNAL_FILE = os.path.join(_BRIDGE_DIR, "latest_signal.json")
_SIGNALS_CSV_FILE = os.path.join(_BRIDGE_DIR, "signals_history.csv")
_EA_FILE = os.path.join(_BRIDGE_DIR, "GoldScalper_MT5_EA.mq5")


DEFAULT_CONFIG = {
    "auto_trading": False,            # معامله خودکار فعال/غیرفعال
    "account_login": "",             # شماره حساب متاتریدر
    "broker_server": "",             # نام سرور بروکر
    "terminal_path": r"C:\Program Files\MetaTrader 5\terminal64.exe",
    "symbol": "XAUUSD",              # نماد طلا در بروکر
    "lot_size": 0.01,                # حجم هر معامله اسکلپ
    "max_daily_positions": 3,        # حداکثر تعداد پوزیشن در روز
    "slippage_points": 20,           # حداکثر اسلیپیج مجاز (پوینت)
    "magic_number": 987654,          # کد شناسایی معاملات اکسپرت
    "status": "not_installed"        # وضعیت اتصال
}


def _ensure_bridge():
    os.makedirs(_BRIDGE_DIR, exist_ok=True)
    if not os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    if not os.path.exists(_EA_FILE):
        _generate_mql5_ea()


def load_config() -> dict:
    """بارگذاری تنظیمات متاتریدر"""
    _ensure_bridge()
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # پر کردن فیلدهای پیش‌فرض اگر اضافه شده باشد
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> bool:
    """ذخیره تنظیمات متاتریدر"""
    os.makedirs(_BRIDGE_DIR, exist_ok=True)
    try:
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[MT5Bridge] Error saving config: {e}")
        return False



def check_mt5_installation() -> dict:
    """
    بررسی وضعیت نصب و آمادگی متاتریدر ۵ روی سیستم کاربر.
    """
    cfg = load_config()
    terminal_path = cfg.get("terminal_path", "")

    # مسیرهای رایج متاتریدر
    common_paths = [
        terminal_path,
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal.exe",
        r"C:\Program Files\MetaTrader 5 IC Markets\terminal64.exe",
    ]

    installed = False
    found_path = ""
    for path in common_paths:
        if path and os.path.isfile(path):
            installed = True
            found_path = path
            break

    # بررسی پکیج پایتون
    python_mt5_installed = False
    try:
        import MetaTrader5 as mt5
        python_mt5_installed = True
    except ImportError:
        pass

    if installed:
        status_text = "آماده اتصال به ترمینال MT5"
        status_code = "ready"
    else:
        status_text = "متاتریدر ۵ فعلاً روی سیستم نصب نیست (پل ارتباطی فایلی فعال است)"
        status_code = "not_installed"

    return {
        "installed": installed,
        "terminal_path": found_path or terminal_path,
        "python_package": python_mt5_installed,
        "status_code": status_code,
        "status_text": status_text,
        "auto_trading_enabled": cfg.get("auto_trading", False),
        "lot_size": cfg.get("lot_size", 0.01),
        "bridge_file": _LATEST_SIGNAL_FILE,
        "ea_file": _EA_FILE
    }


def export_signal_to_bridge(signal_data: dict) -> bool:
    """
    ارسال سیگنال اسکلپ به پل ارتباطی متاتریدر.
    سیگنال در یک فایل استاندارد JSON و CSV نوشته می‌شود تا
    اکسپرت متاتریدر (GoldScalper_MT5_EA) یا پایتون بلافاصله آن را اجرا کند.
    """
    _ensure_bridge()
    if not signal_data or signal_data.get("signal") not in ("BUY", "SELL"):
        return False

    # فیلتر امنیتی اکسپرت: فقط سیگنال‌های با گرید A+، A و B+ با اطمینان بالای ۷۰٪ صادر می‌شوند
    grade = signal_data.get("grade", "D")
    conf = int(signal_data.get("confidence") or 0)
    if grade in ("C", "D") or conf < 70:
        return False

    cfg = load_config()

    bridge_payload = {
        "id": f"XAU_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "symbol": cfg.get("symbol", "XAUUSD"),
        "action": signal_data.get("signal"),
        "grade": signal_data.get("grade", "A"),
        "confidence": signal_data.get("confidence", 70),
        "entry_price": float(signal_data.get("entry", 0.0)),
        "stop_loss": float(signal_data.get("sl", 0.0)),
        "take_profit_1": float(signal_data.get("tp1", 0.0)),
        "take_profit_2": float(signal_data.get("tp2", 0.0)),
        "take_profit_3": float(signal_data.get("tp3", 0.0)),
        "lot_size": float(cfg.get("lot_size", 0.01)),
        "magic_number": int(cfg.get("magic_number", 987654)),
        "slippage": int(cfg.get("slippage_points", 20)),
        "auto_trade": bool(cfg.get("auto_trading", False)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "NEW"  # NEW -> READ -> EXECUTED
    }

    try:
        # ۱. ذخیره در فایل JSON برای خواندن آنی اکسپرت
        with open(_LATEST_SIGNAL_FILE, "w", encoding="utf-8") as f:
            json.dump(bridge_payload, f, ensure_ascii=False, indent=2)

        # ۱.۱ کپی اتوماتیک فایل سیگنال به پوشه Files متاتریدر ۵
        try:
            import glob, shutil
            appdata = os.environ.get('APPDATA')
            if appdata:
                terminals = glob.glob(os.path.join(appdata, 'MetaQuotes', 'Terminal', '*'))
                for t in terminals:
                    files_dir = os.path.join(t, 'MQL5', 'Files')
                    if os.path.isdir(files_dir):
                        shutil.copy2(_LATEST_SIGNAL_FILE, os.path.join(files_dir, "latest_signal.json"))
        except Exception as e:
            print(f"Error copying to MT5 Files: {e}")

        # ۲. ثبت در تاریخچه CSV
        file_exists = os.path.exists(_SIGNALS_CSV_FILE)
        with open(_SIGNALS_CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["ID", "Timestamp", "Action", "Entry", "SL", "TP1", "TP2", "Grade", "AutoTrade"])
            writer.writerow([
                bridge_payload["id"],
                bridge_payload["timestamp"],
                bridge_payload["action"],
                bridge_payload["entry_price"],
                bridge_payload["stop_loss"],
                bridge_payload["take_profit_1"],
                bridge_payload["take_profit_2"],
                bridge_payload["grade"],
                bridge_payload["auto_trade"]
            ])

        print(f"[MT5Bridge] Signal exported to bridge: {bridge_payload['action']} @ {bridge_payload['entry_price']}")
        return True
    except Exception as e:
        print(f"[MT5Bridge] Error exporting signal: {e}")
        return False


def get_latest_exported_signal() -> dict | None:
    """دریافت آخرین سیگنال صادر شده به پل متاتریدر"""
    if not os.path.exists(_LATEST_SIGNAL_FILE):
        return None
    try:
        with open(_LATEST_SIGNAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _generate_mql5_ea():
    """تولید اکسپرت اختصاصی MQL5 برای MetaTrader 5"""
    ea_code = """//+------------------------------------------------------------------+
//|                                        GoldScalper_MT5_EA.mq5    |
//|                        Gold Analyzer Automated Trading Bridge     |
//|                                  Copyright 2026, Gold Analyzer   |
//+------------------------------------------------------------------+
#property copyright "Gold Analyzer"
#property link      "https://localhost"
#property version   "1.00"
#property strict

#include <Trade\\Trade.mqh>

input string   InpJsonPath    = "latest_signal.json"; // Signal JSON File Name (in MQL5\\Files)
input ulong    InpMagicNumber = 987654;               // Magic Number
input double   InpDefaultLot  = 0.01;                 // Default Lot Size
input ulong    InpSlippage    = 20;                   // Slippage in points
input int      InpCheckTimer  = 1;                    // Check interval (seconds)

CTrade         trade;
string         g_last_signal_id = "";

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);

   EventSetTimer(InpCheckTimer);
   Print("⚜ Gold Analyzer MT5 Bridge EA initialized successfully on ", _Symbol);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
}

//+------------------------------------------------------------------+
//| Timer function                                                   |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Check for signal file in MQL5\\Files
   int file_handle = FileOpen(InpJsonPath, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(file_handle == INVALID_HANDLE)
   {
      file_handle = FileOpen(InpJsonPath, FILE_READ|FILE_TXT|FILE_ANSI);
   }

   if(file_handle != INVALID_HANDLE)
   {
      string content = "";
      while(!FileIsEnding(file_handle))
      {
         content += FileReadString(file_handle);
      }
      FileClose(file_handle);

      if(StringLen(content) > 10)
      {
         ProcessSignalJson(content);
      }
   }
}

//+------------------------------------------------------------------+
//| Simple JSON parser helper for trade signal                       |
//+------------------------------------------------------------------+
void ProcessSignalJson(string json)
{
   string sig_id = ExtractJsonValue(json, "id");
   if(sig_id == "" || sig_id == g_last_signal_id) return;

   string action    = ExtractJsonValue(json, "action");
   string auto_tr   = ExtractJsonValue(json, "auto_trade");
   double entry     = StringToDouble(ExtractJsonValue(json, "entry_price"));
   double sl        = StringToDouble(ExtractJsonValue(json, "stop_loss"));
   double tp1       = StringToDouble(ExtractJsonValue(json, "take_profit_1"));
   double lot       = StringToDouble(ExtractJsonValue(json, "lot_size"));

   if(lot <= 0) lot = InpDefaultLot;

   if(auto_tr != "true" && auto_tr != "True" && auto_tr != "1")
   {
      Print("Signal received (", sig_id, ") but auto_trade is disabled in settings.");
      g_last_signal_id = sig_id;
      return;
   }

   // Execute Trade
   if(action == "BUY")
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(trade.Buy(lot, _Symbol, ask, sl, tp1, "Gold Analyzer Scalp BUY"))
      {
         Print("✅ BUY Order Placed: Ticket #", trade.ResultOrder(), " at ", ask, " SL: ", sl, " TP: ", tp1);
         g_last_signal_id = sig_id;
      }
      else
      {
         Print("❌ BUY Order Failed: ", trade.ResultRetcodeDescription());
      }
   }
   else if(action == "SELL")
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(trade.Sell(lot, _Symbol, bid, sl, tp1, "Gold Analyzer Scalp SELL"))
      {
         Print("✅ SELL Order Placed: Ticket #", trade.ResultOrder(), " at ", bid, " SL: ", sl, " TP: ", tp1);
         g_last_signal_id = sig_id;
      }
      else
      {
         Print("❌ SELL Order Failed: ", trade.ResultRetcodeDescription());
      }
   }
}

string ExtractJsonValue(string json, string key)
{
   string search = "\\"" + key + "\\":";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);

   while(pos < StringLen(json) && (StringGetCharacter(json, pos) == ' ' || StringGetCharacter(json, pos) == '\\"'))
      pos++;

   int end_pos = pos;
   while(end_pos < StringLen(json) &&
         StringGetCharacter(json, end_pos) != ',' &&
         StringGetCharacter(json, end_pos) != '}' &&
         StringGetCharacter(json, end_pos) != '\\"')
   {
      end_pos++;
   }

   return StringSubstr(json, pos, end_pos - pos);
}
"""
    try:
        with open(_EA_FILE, "w", encoding="utf-8") as f:
            f.write(ea_code)
    except Exception as e:
        print(f"[MT5Bridge] Error generating EA file: {e}")
