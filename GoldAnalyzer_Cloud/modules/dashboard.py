"""
Dashboard Module
-----------------
Rich terminal UI for the Gold Analyzer.
Renders all analysis panels in a structured, color-coded layout.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.rule import Rule
from rich.align import Align
from rich import box
from datetime import datetime
import pytz

console = Console()


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _color_for_direction(direction: str) -> str:
    return {"BUY": "bold green", "SELL": "bold red", "WAIT": "bold yellow"}.get(direction, "white")


def _color_for_bias(bias: str) -> str:
    if "bull" in bias.lower():  return "green"
    if "bear" in bias.lower():  return "red"
    return "yellow"


def _grade_color(grade: str) -> str:
    return {"A": "bold green", "B": "green", "C": "yellow", "D": "red"}.get(grade, "white")


def _trend_color(trend: str) -> str:
    return {"bullish": "green", "bearish": "red", "sideways": "yellow",
            "mixed": "yellow", "unknown": "dim"}.get(trend, "white")


def _pct_bar(value: float, max_val: float = 100, width: int = 20) -> str:
    filled = int((value / max_val) * width) if max_val > 0 else 0
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────

def render_header(current_price: float, timestamp: str):
    now_ir = datetime.now(pytz.timezone("Asia/Tehran")).strftime("%Y/%m/%d  %H:%M")
    now_utc = datetime.now(pytz.UTC).strftime("%H:%M UTC")

    header_text = Text(justify="center")
    header_text.append("⚜️  GOLD ANALYZER  ⚜️\n", style="bold yellow")
    header_text.append("تحلیلگر هوشمند طلا — XAU/USD\n", style="bold white")
    header_text.append(f"قیمت لحظه‌ای: ", style="dim")
    header_text.append(f"${current_price:,.2f}" if current_price else "در حال دریافت...",
                        style="bold cyan")
    header_text.append(f"    |    {now_ir} تهران  |  {now_utc}\n", style="dim")

    console.print(Panel(Align.center(header_text), border_style="yellow", padding=(0, 2)))


# ─────────────────────────────────────────────
# SESSION PANEL
# ─────────────────────────────────────────────

def render_session_panel(session_report: dict):
    timing   = session_report.get("timing", {})
    sessions = session_report.get("all_sessions", [])
    current  = session_report.get("current_session", {})
    today    = session_report.get("today_levels", {})
    ranges   = session_report.get("session_ranges", {})

    # Session status row
    sess_text = Text()
    for s in sessions:
        color  = s["color"] if s["open"] else "dim"
        status = "● OPEN" if s["open"] else "○ closed"
        sess_text.append(f" {s['name']} ", style=f"bold {color}")
        sess_text.append(f"[{status}]  ", style=color)

    # Timing advice
    grade        = timing.get("grade", "?")
    advice       = timing.get("advice", "")
    timing_score = timing.get("score", 0)
    bar          = _pct_bar(timing_score, 5)

    timing_text = Text()
    timing_text.append(f"وضعیت معامله: ", style="bold")
    timing_text.append(f"{grade}  ", style=_grade_color(grade[0] if grade else "D"))
    timing_text.append(f"[{bar}] {timing_score}/5\n", style="cyan")
    timing_text.append(advice, style="italic")

    # Today session H/L table
    hl_table = Table(box=box.SIMPLE, show_header=True, header_style="bold blue",
                     title="سقف/کف سشن‌های امروز")
    hl_table.add_column("سشن",  style="bold", width=18)
    hl_table.add_column("High",  style="green", justify="right")
    hl_table.add_column("Low",   style="red",   justify="right")
    hl_table.add_column("Open",  style="cyan",  justify="right")
    hl_table.add_column("رنج (pts)", style="yellow", justify="right")
    hl_table.add_column("میانگین ۱۰ روزه", style="dim", justify="right")

    sess_labels = {"asia": "آسیا", "london": "لندن", "new_york": "نیویورک"}
    for key, label in sess_labels.items():
        lv = today.get(key, {})
        rv = ranges.get(key, {})
        h  = lv.get("high")
        l  = lv.get("low")
        o  = lv.get("open")
        r  = round(h - l, 2) if h and l else "-"
        avg_r = rv.get("avg_range", "-")
        hl_table.add_row(
            label,
            f"${h:,.2f}" if h else "-",
            f"${l:,.2f}" if l else "-",
            f"${o:,.2f}" if o else "-",
            str(r),
            f"${avg_r}" if avg_r != "-" else "-",
        )

    console.print(Panel(
        Text.assemble(sess_text, "\n\n", timing_text),
        title="[bold cyan]⏰ سشن‌های معاملاتی[/bold cyan]",
        border_style="cyan", padding=(0, 1)
    ))
    console.print(Align.center(hl_table))


# ─────────────────────────────────────────────
# TECHNICAL ANALYSIS PANEL
# ─────────────────────────────────────────────

def render_technical_panel(ta_report: dict):
    lv     = ta_report.get("latest_values", {})
    scores = ta_report.get("scores", {})
    mtf    = ta_report.get("mtf_trend", {})
    kl     = ta_report.get("key_levels", {})
    pats   = ta_report.get("patterns", {})

    # Indicator values table
    ind_table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta",
                      title="اندیکاتورهای کلیدی (H1)")
    ind_table.add_column("اندیکاتور", style="bold", width=18)
    ind_table.add_column("مقدار", justify="right", width=12)
    ind_table.add_column("وضعیت", width=22)

    def _rsi_status(v):
        if v is None: return "N/A", "dim"
        if v < 30:    return "اشباع فروش ↑", "bold green"
        if v > 70:    return "اشباع خرید ↓", "bold red"
        if v < 45:    return "ضعیف", "yellow"
        if v > 55:    return "قوی", "green"
        return "خنثی", "white"

    rsi   = lv.get("RSI");   rsi_s, rsi_c = _rsi_status(rsi)
    macdh = lv.get("MACD_Hist")
    stk   = lv.get("Stoch_K")
    atr   = lv.get("ATR")
    close = lv.get("Close")
    e9    = lv.get("EMA_9");  e21 = lv.get("EMA_21")
    e50   = lv.get("EMA_50"); e200= lv.get("EMA_200")
    bbu   = lv.get("BB_Upper"); bbl = lv.get("BB_Lower")

    ind_table.add_row("RSI (14)",
                      f"{rsi:.1f}" if rsi else "-",
                      Text(rsi_s, style=rsi_c))

    macd_s = "صعودی ↑" if (macdh and macdh > 0) else ("نزولی ↓" if macdh else "-")
    macd_c = "green"  if (macdh and macdh > 0) else "red"
    ind_table.add_row("MACD Hist",
                      f"{macdh:.3f}" if macdh else "-",
                      Text(macd_s, style=macd_c))

    stk_s = "اشباع فروش" if (stk and stk < 20) else ("اشباع خرید" if (stk and stk > 80) else "خنثی")
    ind_table.add_row("Stochastic %K",
                      f"{stk:.1f}" if stk else "-",
                      stk_s)

    ind_table.add_row("ATR (14)",
                      f"${atr:.2f}" if atr else "-",
                      "نوسان لحظه‌ای")

    if close and e200:
        pos_c = "green" if close > e200 else "red"
        pos_s = "↑ بالای EMA200" if close > e200 else "↓ زیر EMA200"
        ind_table.add_row("EMA 200",
                          f"${e200:.1f}" if e200 else "-",
                          Text(pos_s, style=pos_c))

    if e9 and e21:
        cross = "EMA9>EMA21 ↑" if e9 > e21 else "EMA9<EMA21 ↓"
        cross_c = "green" if e9 > e21 else "red"
        ind_table.add_row("EMA 9 vs 21",
                          f"{e9:.1f} / {e21:.1f}",
                          Text(cross, style=cross_c))

    if bbu and bbl and close:
        bb_pos = "نزدیک باند بالا" if close > bbu * 0.998 else \
                 "نزدیک باند پایین" if close < bbl * 1.002 else "داخل باندها"
        ind_table.add_row("Bollinger",
                          f"{bbl:.1f}–{bbu:.1f}",
                          bb_pos)

    # MTF trend table
    mtf_table = Table(box=box.SIMPLE, show_header=True, header_style="bold blue",
                      title="روند چندتایم‌فریمی")
    mtf_table.add_column("تایم‌فریم", style="bold", width=12)
    mtf_table.add_column("روند",      width=12)
    mtf_table.add_column("قدرت",      justify="right", width=8)

    for tf_key, tf_label in [("daily","روزانه"), ("h4","H4"), ("h1","H1")]:
        tr = mtf.get(tf_key, {})
        d  = tr.get("direction", "?")
        s  = tr.get("strength", 0)
        mtf_table.add_row(
            tf_label,
            Text(d, style=_trend_color(d)),
            f"{s}%"
        )
    overall = mtf.get("overall", "mixed")
    mtf_table.add_row(
        "[bold]کل[/bold]",
        Text(overall, style=_trend_color(overall) + " bold"),
        ""
    )

    # Score bar table
    score_table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan",
                        title="امتیاز تکنیکال هر تایم‌فریم")
    score_table.add_column("TF", width=8, style="bold")
    score_table.add_column("Score", justify="right", width=8)
    score_table.add_column("Bias", width=12)

    for tf_key, tf_label in [("daily","D1"), ("h4","H4"), ("h1","H1"), ("m15","M15")]:
        sc = scores.get(tf_key, {})
        raw  = sc.get("score", 0)
        bias = sc.get("bias", "neutral")
        bc   = "green" if bias == "bullish" else "red" if bias == "bearish" else "yellow"
        score_table.add_row(tf_label, str(raw), Text(bias, style=bc))

    # Patterns
    all_p = pats.get("h1", []) + pats.get("m15", [])
    pat_text = Text()
    if all_p:
        pat_text.append("🕯️ الگوهای کندلی: ", style="bold")
        for p in all_p:
            c = "green" if "bull" in p.lower() or "hammer" in p.lower() else \
                "red"   if "bear" in p.lower() or "shooting" in p.lower() else "yellow"
            pat_text.append(f"  • {p}\n", style=c)
    else:
        pat_text.append("کندل خاصی شناسایی نشد", style="dim")

    # Key levels
    kl_text = Text()
    pivots   = kl.get("pivot_points", {})
    swings   = kl.get("hourly_swing", {})
    if pivots:
        kl_text.append("🔵 Pivot Points: ", style="bold blue")
        kl_text.append(f"PP={pivots.get('PP','-')}  "
                       f"R1={pivots.get('R1','-')}  R2={pivots.get('R2','-')}  "
                       f"S1={pivots.get('S1','-')}  S2={pivots.get('S2','-')}\n", style="cyan")
    if swings:
        res = swings.get("resistance", [])
        sup = swings.get("support", [])
        kl_text.append("🔴 مقاومت: ", style="bold red")
        kl_text.append("  ".join([f"${r}" for r in res[:3]]) + "\n", style="red")
        kl_text.append("🟢 حمایت:  ", style="bold green")
        kl_text.append("  ".join([f"${s}" for s in sup[:3]]) + "\n", style="green")

    console.print(Panel(
        Columns([ind_table, mtf_table, score_table], equal=False, expand=True),
        title="[bold magenta]📊 تحلیل تکنیکال[/bold magenta]",
        border_style="magenta", padding=(0, 1)
    ))
    console.print(Panel(
        Text.assemble(pat_text, "\n", kl_text),
        title="[bold blue]🔑 الگوها و سطوح کلیدی[/bold blue]",
        border_style="blue", padding=(0, 1)
    ))


# ─────────────────────────────────────────────
# FUNDAMENTAL PANEL
# ─────────────────────────────────────────────

def render_fundamental_panel(fa_report: dict):
    bias   = fa_report.get("bias_label", "")
    score  = fa_report.get("total_score", 0)
    comps  = fa_report.get("components", {})

    rows_text = Text()

    # DXY
    dxy = comps.get("dxy", {})
    dxy_c = "green" if "bull" in dxy.get("signal","") else "red" if "bear" in dxy.get("signal","") else "yellow"
    rows_text.append("💵 DXY:           ", style="bold")
    rows_text.append(f"{dxy.get('current','-')} | {dxy.get('trend','-')} | ", style=dxy_c)
    rows_text.append(f"{dxy.get('note','')}\n", style="dim")

    # Yields
    yields = comps.get("yields", {})
    y_c = "green" if "bull" in yields.get("signal","") else "red" if "bear" in yields.get("signal","") else "yellow"
    rows_text.append("🏦 بازده ۱۰ ساله: ", style="bold")
    rows_text.append(f"{yields.get('current','-')}%  Δ{yields.get('change','-')} | ", style=y_c)
    rows_text.append(f"{yields.get('note','')}\n", style="dim")

    # Risk sentiment
    risk = comps.get("risk_sentiment", {})
    r_c = "green" if "bull" in risk.get("signal","") else "red" if "bear" in risk.get("signal","") else "yellow"
    rows_text.append("📉 S&P500:         ", style="bold")
    rows_text.append(f"{risk.get('sp500','-')} | Δ5d: {risk.get('change_5d','-')}% | {risk.get('mode','-')}\n", style=r_c)
    rows_text.append(f"   {risk.get('note','')}\n", style="dim")

    # Geopolitical
    geo = comps.get("geopolitical", {})
    g_c = "red" if geo.get("level") in ("high","critical") else "yellow" if geo.get("level") == "moderate" else "green"
    rows_text.append("🌍 ژئوپلیتیک:     ", style="bold")
    rows_text.append(f"{geo.get('note','')}\n", style=g_c)

    # News sentiment
    sent = comps.get("news_sentiment", {})
    s_c  = "green" if sent.get("sentiment") == "bullish" else "red" if sent.get("sentiment") == "bearish" else "yellow"
    rows_text.append("📰 احساس اخبار:   ", style="bold")
    rows_text.append(f"{sent.get('sentiment','?')} ({sent.get('confidence',0)}% اطمینان)\n", style=s_c)

    # Calendar
    cal = comps.get("calendar", {})
    cal_c = "red" if cal.get("risk_level") in ("high","very_high") else "yellow" if cal.get("risk_level") == "medium" else "green"
    rows_text.append("📅 تقویم:          ", style="bold")
    rows_text.append(f"{cal.get('note','')}\n", style=cal_c)

    if cal.get("upcoming"):
        rows_text.append("\n رویدادهای پیش‌رو:\n", style="bold dim")
        for ev in cal["upcoming"][:3]:
            impact_c = "red" if ev.get("impact") == "high" else "yellow"
            rows_text.append(f"   ⚡ [{ev.get('country','')}] {ev.get('title','')} "
                             f"— {ev.get('date','')} {ev.get('time','')}\n",
                             style=impact_c)

    # Overall bias bar
    bias_c = _color_for_bias(fa_report.get("bias","neutral"))
    fa_bar = _pct_bar(abs(score), 10)
    direction_label = "↑ صعودی" if score > 0 else ("↓ نزولی" if score < 0 else "→ خنثی")

    footer = Text()
    footer.append(f"\n  فاندامنتال کلی: ", style="bold")
    footer.append(f"{bias}  ", style=bias_c)
    footer.append(f"[{fa_bar}] {direction_label} امتیاز={score:.1f}", style=bias_c)

    console.print(Panel(
        Text.assemble(rows_text, footer),
        title="[bold yellow]💰 تحلیل فاندامنتال[/bold yellow]",
        border_style="yellow", padding=(0, 1)
    ))


# ─────────────────────────────────────────────
# NEWS PANEL
# ─────────────────────────────────────────────

def render_news_panel(news_items: list):
    if not news_items:
        console.print(Panel("اخباری یافت نشد", title="📰 اخبار بازار", border_style="blue"))
        return

    news_text = Text()
    for i, item in enumerate(news_items[:8], 1):
        rel   = item.get("relevance", 0)
        color = "bold red" if rel >= 6 else "yellow" if rel >= 3 else "dim"
        tag   = "🔴 HIGH" if rel >= 6 else "🟡 MED" if rel >= 3 else "⚪ LOW"
        title = item.get("title", "")[:90]
        pub   = item.get("published", "")[:16]
        src   = item.get("source", "")[:20]
        news_text.append(f"  {i}. [{tag}]  ", style=color)
        news_text.append(f"{title}\n", style="white")
        news_text.append(f"     📡 {src}  |  🕐 {pub}\n\n", style="dim")

    console.print(Panel(
        news_text,
        title="[bold blue]📰 اخبار مرتبط با طلا[/bold blue]",
        border_style="blue", padding=(0, 1)
    ))


# ─────────────────────────────────────────────
# SIGNAL PANEL  (Main output)
# ─────────────────────────────────────────────

def render_signal_panel(signal: dict):
    direction = signal.get("signal", "WAIT")
    grade     = signal.get("grade", "D")
    conf      = signal.get("confidence", 0)
    label     = signal.get("label", "")
    entry     = signal.get("entry")
    sl        = signal.get("sl")
    tp1       = signal.get("tp1")
    tp2       = signal.get("tp2")
    tp3       = signal.get("tp3")
    rr1       = signal.get("rr1", 0)
    rr2       = signal.get("rr2", 0)
    rr3       = signal.get("rr3", 0)
    atr       = signal.get("atr")
    sizing    = signal.get("position_size", {}) or {}
    reasoning = signal.get("reasoning", [])
    warnings  = signal.get("warnings", [])
    net_score = signal.get("net_score", 0)

    sig_color = _color_for_direction(direction)
    sig_emoji = {"BUY": "🟢 BUY ▲", "SELL": "🔴 SELL ▼", "WAIT": "⏸️  WAIT"}.get(direction, direction)

    # ── Top signal box ──
    top = Text(justify="center")
    top.append(f"\n  {sig_emoji}  ", style=sig_color + " bold")
    top.append(f"  گرید: ", style="bold")
    top.append(f"{grade}  ", style=_grade_color(grade))
    top.append(f"  اطمینان: ", style="bold")
    top.append(f"{conf}%  ", style="cyan")
    conf_bar = _pct_bar(conf, 100, 25)
    top.append(f"[{conf_bar}]\n", style="cyan")
    top.append(f"  {label}\n", style="italic")

    if direction == "WAIT":
        console.print(Panel(Align.center(top),
                            title="[bold]🎯 سیگنال معاملاتی[/bold]",
                            border_style="yellow", padding=(0, 2)))
        _render_reasoning(reasoning)
        return

    # ── Levels table ──
    levels_table = Table(box=box.ROUNDED, show_header=True,
                         header_style="bold white", title="سطوح معاملاتی")
    levels_table.add_column("سطح",       style="bold",  width=16)
    levels_table.add_column("قیمت",      justify="right", width=14, style="bold cyan")
    levels_table.add_column("فاصله",     justify="right", width=12)
    levels_table.add_column("R:R",       justify="right", width=8)
    levels_table.add_column("توضیح",     width=22)

    risk_pts = signal.get("risk_pips", 0)

    levels_table.add_row(
        "🎯 ورود (Entry)",
        f"${entry:,.2f}" if entry else "-",
        "-", "-",
        "قیمت ورود به معامله"
    )
    levels_table.add_row(
        "🛑 حد ضرر (SL)",
        f"${sl:,.2f}" if sl else "-",
        f"{risk_pts:.2f} pts",
        "-",
        Text("زیر سویینگ/حمایت", style="red")
    )
    levels_table.add_row(
        "🥇 هدف اول (TP1)",
        f"${tp1:,.2f}" if tp1 else "-",
        f"{abs(tp1-entry):.2f} pts" if tp1 and entry else "-",
        f"1:{rr1}",
        Text("بستن ۵۰٪ معامله اینجا", style="green")
    )
    levels_table.add_row(
        "🥈 هدف دوم (TP2)",
        f"${tp2:,.2f}" if tp2 else "-",
        f"{abs(tp2-entry):.2f} pts" if tp2 and entry else "-",
        f"1:{rr2}",
        Text("بستن ۳۰٪ معامله اینجا", style="green")
    )
    levels_table.add_row(
        "🥉 هدف سوم (TP3)",
        f"${tp3:,.2f}" if tp3 else "-",
        f"{abs(tp3-entry):.2f} pts" if tp3 and entry else "-",
        f"1:{rr3}",
        Text("باقی‌مانده معامله (runner)", style="yellow")
    )

    # ── Position sizing ──
    size_text = Text()
    if sizing:
        size_text.append("\n  💼 پیشنهاد حجم (حساب $10,000 | ریسک 1%):\n", style="bold")
        size_text.append(f"     لات: {sizing.get('lots', '-')}  |  "
                         f"ریسک: ${sizing.get('risk_usd', '-')}  |  "
                         f"SL فاصله: {sizing.get('sl_distance', '-')} pts\n", style="cyan")
        size_text.append(f"     ⚠️ این صرفاً پیشنهاد است — مدیریت سرمایه خودتان را داشته باشید\n",
                         style="dim italic")

    # ── Score breakdown ──
    score_text = Text()
    score_text.append(f"\n  امتیاز کلی: ", style="bold")
    sig_c = "green" if net_score > 0 else "red"
    score_text.append(f"{net_score:+.1f}  ", style=sig_c + " bold")
    score_text.append(f"(خرید: {signal.get('buy_score',0):.1f} | فروش: {signal.get('sell_score',0):.1f})\n",
                      style="dim")
    if atr:
        score_text.append(f"  ATR فعلی: ${atr:.2f}  |  ", style="dim")
    score_text.append(f"تایم‌استمپ: {signal.get('timestamp','')}\n", style="dim")

    console.print(Panel(
        Text.assemble(Align.center(top), "\n"),
        title=f"[{sig_color}]🎯 سیگنال معاملاتی — {direction}[/{sig_color}]",
        border_style=sig_color.replace("bold ", ""), padding=(0, 2)
    ))
    console.print(Align.center(levels_table))
    console.print(Panel(
        Text.assemble(size_text, score_text),
        border_style="dim", padding=(0, 1)
    ))

    # Warnings
    if warnings:
        warn_text = Text()
        for w in warnings:
            warn_text.append(f"  {w}\n", style="bold yellow")
        console.print(Panel(warn_text, title="⚠️  هشدارها", border_style="yellow"))

    _render_reasoning(reasoning)


def _render_reasoning(reasoning: list):
    if not reasoning:
        return
    reason_text = Text()
    for line in reasoning:
        if line.startswith("🟢") or line.startswith("✅"):
            reason_text.append(f"  {line}\n", style="green")
        elif line.startswith("🔴") or line.startswith("⛔"):
            reason_text.append(f"  {line}\n", style="red")
        elif line.startswith("⚠️"):
            reason_text.append(f"  {line}\n", style="yellow")
        elif line.startswith("   •"):
            reason_text.append(f"{line}\n", style="dim italic")
        else:
            reason_text.append(f"  {line}\n", style="white")

    console.print(Panel(
        reason_text,
        title="[bold]📋 دلایل سیگنال[/bold]",
        border_style="dim white", padding=(0, 1)
    ))


# ─────────────────────────────────────────────
# SCORE BREAKDOWN PANEL
# ─────────────────────────────────────────────

def render_score_breakdown(signal: dict):
    details = signal.get("score_details", [])
    if not details:
        return

    detail_text = Text()
    for d in details:
        if "صعودی" in d or "+": 
            c = "green" if "صعودی" in d else "red" if "نزولی" in d else "yellow"
        else:
            c = "white"
        detail_text.append(f"  • {d}\n", style=c)

    console.print(Panel(
        detail_text,
        title="[dim]📊 جزئیات امتیازدهی[/dim]",
        border_style="dim", padding=(0, 1)
    ))


# ─────────────────────────────────────────────
# FULL DASHBOARD RENDER
# ─────────────────────────────────────────────

def render_full_dashboard(signal: dict, snapshot: dict):
    """Master render function — draws the entire dashboard."""
    console.clear()

    current_price = snapshot.get("current", {}).get("price")
    timestamp     = signal.get("timestamp", "")

    ta_report      = signal.get("ta_report", {})
    fa_report      = signal.get("fa_report", {})
    session_report = signal.get("session_report", {})
    news_items     = snapshot.get("news", [])

    render_header(current_price, timestamp)
    console.print()
    render_signal_panel(signal)
    console.print()
    render_session_panel(session_report)
    console.print()
    render_technical_panel(ta_report)
    console.print()
    render_fundamental_panel(fa_report)
    console.print()
    render_news_panel(news_items)
    console.print()
    render_score_breakdown(signal)

    console.print(Rule("[dim]آخرین به‌روزرسانی: " + timestamp + "[/dim]"))
