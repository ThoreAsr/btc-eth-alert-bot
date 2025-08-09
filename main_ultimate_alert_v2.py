import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# =============== CONFIG ===============
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"

# MEXC 15m, 120 candele (≈ 30 ore)
KLINE_URL = "https://api.mexc.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=120"

# TP/SL dinamici (percentuali dall’entry)
TP_PCT = 1.0
SL_PCT = 0.3

# Cooldown anti-spam (secondi)
WEAK_ALERT_COOLDOWN = 10 * 60   # 10 min
STRONG_ALERT_COOLDOWN = 15 * 60 # 15 min

# =============== STATO ===============
state = {
    "BTC": {
        "last_strong_dir": None,
        "last_weak_kind": None,
        "last_strong_ts": 0.0,
        "last_weak_ts": 0.0,
        "last_report_sig": None,
        "last_report_ts": 0.0,
        "active_trade": None,
    },
    "ETH": {
        "last_strong_dir": None,
        "last_weak_kind": None,
        "last_strong_ts": 0.0,
        "last_weak_ts": 0.0,
        "last_report_sig": None,
        "last_report_ts": 0.0,
        "active_trade": None,
    },
}

STARTUP_MESSAGE_SENT = False


# =============== UTILITY ===============
def log(msg: str):
    try:
        ts = datetime.now(tz=ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")
        with open("bot_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

def send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=8
        )
    except Exception as e:
        log(f"Telegram error: {e}")

def get_klines(symbol: str):
    try:
        r = requests.get(
            KLINE_URL.format(symbol=symbol),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"Klines error {symbol}: {e}")
        return None

def ema_series(seq, p):
    k = 2 / (p + 1)
    out = []
    ema = seq[0]
    for v in seq:
        ema = v * k + ema * (1 - k)
        out.append(ema)
    return out

def ema_last_and_prev(seq, p):
    ema = ema_series(seq, p)
    return ema[-2], ema[-1]

def atr(closes, highs, lows, period=20):
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
        trs.append(tr)
    if not trs:
        return 0.0
    return ema_series(trs, period)[-1] if len(trs) >= period else trs[-1]

def macd_hist_last(closes):
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    macd_line = [a - b for a, b in zip(ema12[-len(ema26):], ema26)]
    signal = ema_series(macd_line, 9)
    return macd_line[-1] - signal[-1]

def next_half_hour_epoch() -> float:
    """Prossimo tick :00 / :30 SEMPRE nel futuro (fix duplicati)."""
    now = datetime.now(tz=ZoneInfo("UTC"))
    base = now.replace(second=0, microsecond=0)
    add = 30 - (base.minute % 30)
    if add == 0:
        add = 30
    nxt = base + timedelta(minutes=add)
    return nxt.timestamp()

def cooldown_ok(symbol: str, kind: str, seconds: int) -> bool:
    """kind: 'strong' o 'weak' per asset 'symbol'."""
    now = time.time()
    if kind == "strong":
        last = state[symbol]["last_strong_ts"]
        if now - last >= seconds:
            state[symbol]["last_strong_ts"] = now
            return True
        return False
    else:
        last = state[symbol]["last_weak_ts"]
        if now - last >= seconds:
            state[symbol]["last_weak_ts"] = now
            return True
        return False


# =============== ANALISI ===============
def analyze(symbol):
    """
    Ritorna:
    price, open, vol15m, avg_vol15m, ema20, ema20_prev, ema60, hist,
    bull, bear, levels {breakout[], breakdown[]}
    """
    data = get_klines(symbol)
    if not data or len(data) < 60:
        send_telegram(f"⚠️ Errore dati {symbol}")
        return None

    opens  = [float(c[1]) for c in data]
    highs  = [float(c[2]) for c in data]
    lows   = [float(c[3]) for c in data]
    closes = [float(c[4]) for c in data]
    qty    = [float(c[5]) for c in data]  # volume base coin (15m)

    usdt_vol = [closes[i]*qty[i] for i in range(len(closes))]
    vol15m = usdt_vol[-1]
    avg_vol15m = sum(usdt_vol[-48:]) / 48  # media 12h

    last_open, last_close = opens[-1], closes[-1]
    bull = last_close > last_open
    bear = last_close < last_open

    ema20_prev, ema20 = ema_last_and_prev(closes[-60:], 20)
    ema60 = ema_series(closes[-60:], 60)[-1]
    hist = macd_hist_last(closes[-120:])

    # Volatilità e livelli dinamici: swing 24h + EMA20±ATR
    atr20 = atr(closes[-60:], highs[-60:], lows[-60:], 20)
    swing_high = max(highs[-96:])  # ≈ 24h
    swing_low  = min(lows[-96:])

    breakout_levels  = sorted(set([round(swing_high, 2), round(ema20 + atr20, 2)]))
    breakdown_levels = sorted(set([round(swing_low, 2),  round(ema20 - atr20, 2)]), reverse=True)

    return {
        "price": last_close,
        "open": last_open,
        "vol15m": vol15m,
        "avg_vol15m": avg_vol15m,
        "ema20": ema20,
        "ema20_prev": ema20_prev,
        "ema60": ema60,
        "hist": hist,
        "bull": bull,
        "bear": bear,
        "levels": {"breakout": breakout_levels, "breakdown": breakdown_levels}
    }


# =============== TRADE ===============
def open_trade(symbol, direction, entry_price):
    if direction == "LONG":
        tp = entry_price * (1 + TP_PCT/100)
        sl = entry_price * (1 - SL_PCT/100)
    else:
        tp = entry_price * (1 - TP_PCT/100)
        sl = entry_price * (1 + SL_PCT/100)

    state[symbol]["active_trade"] = {"direction": direction, "entry": entry_price, "tp": tp, "sl": sl}
    send_telegram(
        f"🔥 SEGNALE FORTISSIMO {direction} {symbol}\n"
        f"Entra: {round(entry_price,2)} | Target: {round(tp,2)} | Stop: {round(sl,2)}"
    )
    log(f"Open {direction} {symbol} entry={entry_price} tp={tp} sl={sl}")

def monitor_trade(symbol, price):
    trade = state[symbol]["active_trade"]
    if not trade:
        return
    direction, tp, sl = trade["direction"], trade["tp"], trade["sl"]
    if direction == "LONG":
        if price >= tp:
            send_telegram(f"✅ TP raggiunto LONG {symbol} a {round(tp,2)}")
            state[symbol]["active_trade"] = None
        elif price <= sl:
            send_telegram(f"❌ STOP colpito LONG {symbol} a {round(sl,2)}")
            state[symbol]["active_trade"] = None
    else:
        if price <= tp:
            send_telegram(f"✅ TP raggiunto SHORT {symbol} a {round(tp,2)}")
            state[symbol]["active_trade"] = None
        elif price >= sl:
            send_telegram(f"❌ STOP colpito SHORT {symbol} a {round(sl,2)}")
            state[symbol]["active_trade"] = None


# =============== SIGNALS ===============
def check_signal(symbol, a):
    p = a["price"]
    v = a["vol15m"]
    avg_v = a["avg_vol15m"]
    ema20, ema20_prev, ema60 = a["ema20"], a["ema20_prev"], a["ema60"]
    hist = a["hist"]
    bull, bear = a["bull"], a["bear"]
    levels = a["levels"]

    vol_ok = v >= 1.2 * avg_v  # volume corrente >= 120% della media 12h

    # ---- LONG (breakout) ----
    for lvl in levels["breakout"]:
        if p >= lvl:
            trend_ok     = ema20 > ema60
            slope_ok     = ema20 > ema20_prev
            candle_ok    = bull
            macd_ok      = hist > 0
            above_ema_ok = p >= ema20

            if trend_ok and slope_ok and candle_ok and macd_ok and above_ema_ok:
                if vol_ok and cooldown_ok(symbol, "strong", STRONG_ALERT_COOLDOWN):
                    if state[symbol]["last_strong_dir"] != "LONG":
                        open_trade(symbol, "LONG", p)
                        state[symbol]["last_strong_dir"] = "LONG"
                elif (not vol_ok) and cooldown_ok(symbol, "weak", WEAK_ALERT_COOLDOWN):
                    send_telegram(f"⚠️ Breakout debole {symbol} | {round(p,2)}$ | Vol 15m {round(v/1e6,1)}M")

    # ---- SHORT (breakdown) ----
    for lvl in levels["breakdown"]:
        if p <= lvl:
            trend_ok     = ema20 < ema60
            slope_ok     = ema20 < ema20_prev
            candle_ok    = bear
            macd_ok      = hist < 0
            below_ema_ok = p <= ema20

            if trend_ok and slope_ok and candle_ok and macd_ok and below_ema_ok:
                if vol_ok and cooldown_ok(symbol, "strong", STRONG_ALERT_COOLDOWN):
                    if state[symbol]["last_strong_dir"] != "SHORT":
                        open_trade(symbol, "SHORT", p)
                        state[symbol]["last_strong_dir"] = "SHORT"
                elif (not vol_ok) and cooldown_ok(symbol, "weak", WEAK_ALERT_COOLDOWN):
                    send_telegram(f"⚠️ Breakdown debole {symbol} | {round(p,2)}$ | Vol 15m {round(v/1e6,1)}M")

    # reset direzione se rientra nella zona centrale
    bo_min = min(levels["breakout"])
    bd_max = max(levels["breakdown"])
    if bd_max < p < bo_min:
        state[symbol]["last_strong_dir"] = None


# =============== REPORT ===============
def report_line(symbol, price, ema20, ema60, vol15m, avg_v):
    trend = "🟢" if ema20 > ema60 else "🔴" if ema20 < ema60 else "⚪"
    return f"{trend} {symbol}: {round(price,2)}$ | EMA20:{round(ema20,2)} | EMA60:{round(ema60,2)} | Vol15m:{round(vol15m/1e6,1)}M (avg:{round(avg_v/1e6,1)}M)"

def suggestion(btc_trend, eth_trend):
    if btc_trend == "🟢" and eth_trend == "🟢":
        return "Suggerimento: Preferenza LONG ✅"
    if btc_trend == "🔴" and eth_trend == "🔴":
        return "Suggerimento: Preferenza SHORT ❌"
    return "Suggerimento: Trend misto – Attendere conferma ⚠️"

def build_report():
    trends = {}
    parts = []
    for sym in ["BTC", "ETH"]:
        a = analyze(sym)
        if not a:
            parts.append(f"{sym}: Errore dati")
            trends[sym] = "⚪"
            continue
        parts.append(report_line(sym, a["price"], a["ema20"], a["ema60"], a["vol15m"], a["avg_vol15m"]))
        trends[sym] = "🟢" if a["ema20"] > a["ema60"] else "🔴" if a["ema20"] < a["ema60"] else "⚪"
    sug = suggestion(trends["BTC"], trends["ETH"])
    return parts, sug

def send_report_if_new():
    it = datetime.now(tz=ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M")
    utc = datetime.now(tz=ZoneInfo("UTC")).strftime("%d/%m %H:%M")
    parts, sug = build_report()
    # firma anti-duplicato (arrotondo per stabilità)
    sig = "|".join(parts)

    # se identico all’ultimo inviato < 10 min fa → non invio
    now = time.time()
    last_sig_btc = state["BTC"]["last_report_sig"]
    last_sig_eth = state["ETH"]["last_report_sig"]
    last_ts_btc  = state["BTC"]["last_report_ts"]
    last_ts_eth  = state["ETH"]["last_report_ts"]

    # usiamo stessa firma e timestamp su entrambi (report unico)
    is_dup = (sig == last_sig_btc == last_sig_eth) and (now - min(last_ts_btc, last_ts_eth) < 600)
    if is_dup:
        return

    msg = f"🕒 Report {it} (Italia) | {utc} UTC\n\n" + "\n".join(parts) + f"\n\n{sug}"
    send_telegram(msg)

    state["BTC"]["last_report_sig"] = sig
    state["ETH"]["last_report_sig"] = sig
    state["BTC"]["last_report_ts"]  = now
    state["ETH"]["last_report_ts"]  = now


# =============== MAIN LOOP ===============
if __name__ == "__main__":
    if not STARTUP_MESSAGE_SENT:
        send_telegram("✅ Bot PRO attivo – Segnali Fortissimi con TP/SL dinamici (Apple Watch ready)")
        STARTUP_MESSAGE_SENT = True

    # report immediato, poi allineo a :00 / :30
    report_immediato = True
    next_report_ts = next_half_hour_epoch()

    while True:
        try:
            # Analisi + segnali + monitor
            for sym in ["BTC", "ETH"]:
                a = analyze(sym)
                if not a:
                    continue
                check_signal(sym, a)
                monitor_trade(sym, a["price"])

            # Report: subito al primo giro, poi solo ai :00/:30
            now_utc = time.time()
            if report_immediato or now_utc >= next_report_ts:
                report_immediato = False
                send_report_if_new()
                next_report_ts = next_half_hour_epoch()  # SEMPRE futuro

            time.sleep(5)

        except Exception as e:
            log(f"Loop error: {e}")
            time.sleep(10)
