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

# Cooldown anti-spam
WEAK_ALERT_COOLDOWN = 10 * 60   # 10 min
STRONG_ALERT_COOLDOWN = 15 * 60 # 15 min

# Stato
last_signal = {"BTC": None, "ETH": None}
active_trade = {"BTC": None, "ETH": None}
last_weak_alert_ts = {"BTC_breakout": 0, "BTC_breakdown": 0, "ETH_breakout": 0, "ETH_breakdown": 0}
last_strong_alert_ts = {"BTC_LONG": 0, "BTC_SHORT": 0, "ETH_LONG": 0, "ETH_SHORT": 0}
STARTUP_MESSAGE_SENT = False


# =============== UTIL ===============
def log(msg: str):
    try:
        ts = datetime.now(tz=ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")
        with open("bot_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

def send_telegram(text: str):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text}, timeout=8)
    except Exception as e:
        log(f"Telegram error: {e}")

def get_klines(symbol: str):
    try:
        r = requests.get(KLINE_URL.format(symbol=symbol), headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
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
        tr = max(highs[i]-lows[i],
                 abs(highs[i]-closes[i-1]),
                 abs(lows[i]-closes[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return trs[-1] if trs else 0.0
    # EMA ATR
    return ema_series(trs, period)[-1]

def macd_hist_last(closes):
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    macd_line = [a - b for a, b in zip(ema12[-len(ema26):], ema26)]
    signal = ema_series(macd_line, 9)
    return macd_line[-1] - signal[-1]

def next_half_hour_epoch() -> float:
    now = datetime.now(tz=ZoneInfo("UTC"))
    add = 30 - (now.minute % 30)
    if add == 30:
        add = 0
    t = (now.replace(second=0, microsecond=0) + timedelta(minutes=add))
    return t.timestamp()

def cooldown_ok(dic, key, secs):
    now = time.time()
    if now - dic.get(key, 0) >= secs:
        dic[key] = now
        return True
    return False


# =============== ANALISI ===============
def analyze(symbol):
    """
    Ritorna:
    price, open, vol15m, avg_vol15m, ema20, ema20_prev, ema60, hist,
    bull, bear, dyn_levels {breakout[], breakdown[]}
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
    # media volumi 48*15m ≈ 12 ore (più reattiva del 24h)
    avg_vol15m = sum(usdt_vol[-48:]) / 48

    last_open, last_close = opens[-1], closes[-1]
    bull = last_close > last_open
    bear = last_close < last_open

    ema20_prev, ema20 = ema_last_and_prev(closes[-60:], 20)
    ema60 = ema_series(closes[-60:], 60)[-1]
    hist = macd_hist_last(closes[-120:])

    # Volatilità e livelli dinamici
    atr20 = atr(closes[-60:], highs[-60:], lows[-60:], 20)
    swing_high = max(highs[-96:])  # ≈ 24h
    swing_low  = min(lows[-96:])

    # livelli “primari”: swing 24h; “secondari”: banda EMA20 ± 1*ATR
    breakout_levels = sorted(set([round(swing_high, 2), round(ema20 + atr20, 2)]))
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

    active_trade[symbol] = {"direction": direction, "entry": entry_price, "tp": tp, "sl": sl}
    send_telegram(
        f"🔥 SEGNALE FORTISSIMO {direction} {symbol}\n"
        f"Entra: {round(entry_price,2)} | Target: {round(tp,2)} | Stop: {round(sl,2)}"
    )
    log(f"Open {direction} {symbol} entry={entry_price} tp={tp} sl={sl}")

def monitor_trade(symbol, price):
    trade = active_trade[symbol]
    if not trade:
        return
    direction, tp, sl = trade["direction"], trade["tp"], trade["sl"]
    if direction == "LONG":
        if price >= tp:
            send_telegram(f"✅ TP raggiunto LONG {symbol} a {round(tp,2)}")
            active_trade[symbol] = None
        elif price <= sl:
            send_telegram(f"❌ STOP colpito LONG {symbol} a {round(sl,2)}")
            active_trade[symbol] = None
    else:
        if price <= tp:
            send_telegram(f"✅ TP raggiunto SHORT {symbol} a {round(tp,2)}")
            active_trade[symbol] = None
        elif price >= sl:
            send_telegram(f"❌ STOP colpito SHORT {symbol} a {round(sl,2)}")
            active_trade[symbol] = None


# =============== SIGNALS ===============
def check_signal(symbol, a):
    global last_signal
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
            trend_ok = ema20 > ema60
            slope_ok = ema20 > ema20_prev
            candle_ok = bull
            macd_ok = hist > 0
            above_ema_ok = p >= ema20

            if trend_ok and slope_ok and candle_ok and macd_ok and above_ema_ok:
                if vol_ok and cooldown_ok(last_strong_alert_ts, f"{symbol}_LONG", STRONG_ALERT_COOLDOWN):
                    if last_signal[symbol] != "LONG":
                        open_trade(symbol, "LONG", p)
                        last_signal[symbol] = "LONG"
                elif not vol_ok and cooldown_ok(last_weak_alert_ts, f"{symbol}_breakout", WEAK_ALERT_COOLDOWN):
                    send_telegram(f"⚠️ Breakout debole {symbol} | {round(p,2)}$ | Vol 15m {round(v/1e6,1)}M")

    # ---- SHORT (breakdown) ----
    for lvl in levels["breakdown"]:
        if p <= lvl:
            trend_ok = ema20 < ema60
            slope_ok = ema20 < ema20_prev
            candle_ok = bear
            macd_ok = hist < 0
            below_ema_ok = p <= ema20

            if trend_ok and slope_ok and candle_ok and macd_ok and below_ema_ok:
                if vol_ok and cooldown_ok(last_strong_alert_ts, f"{symbol}_SHORT", STRONG_ALERT_COOLDOWN):
                    if last_signal[symbol] != "SHORT":
                        open_trade(symbol, "SHORT", p)
                        last_signal[symbol] = "SHORT"
                elif not vol_ok and cooldown_ok(last_weak_alert_ts, f"{symbol}_breakdown", WEAK_ALERT_COOLDOWN):
                    send_telegram(f"⚠️ Breakdown debole {symbol} | {round(p,2)}$ | Vol 15m {round(v/1e6,1)}M")

    # reset se in mezzo
    bo = min(levels["breakout"])
    bd = max(levels["breakdown"])
    if bd < p < bo:
        last_signal[symbol] = None


# =============== REPORT ===============
def line(symbol, price, ema20, ema60, vol15m, avgv):
    trend = "🟢" if ema20 > ema60 else "🔴" if ema20 < ema60 else "⚪"
    return f"{trend} {symbol}: {round(price,2)}$ | EMA20:{round(ema20,2)} | EMA60:{round(ema60,2)} | Vol15m:{round(vol15m/1e6,1)}M (avg:{round(avgv/1e6,1)}M)"

def suggestion(btc_trend, eth_trend):
    if btc_trend == "🟢" and eth_trend == "🟢":
        return "Suggerimento: Preferenza LONG ✅"
    if btc_trend == "🔴" and eth_trend == "🔴":
        return "Suggerimento: Preferenza SHORT ❌"
    return "Suggerimento: Trend misto – Attendere conferma ⚠️"


# =============== MAIN LOOP ===============
if __name__ == "__main__":
    if not STARTUP_MESSAGE_SENT:
        send_telegram("✅ Bot PRO attivo – Segnali Fortissimi con TP/SL dinamici (Apple Watch ready)")
        STARTUP_MESSAGE_SENT = True

    report_immediato = True
    next_report_ts = next_half_hour_epoch()

    while True:
        try:
            for sym in ["BTC", "ETH"]:
                a = analyze(sym)
                if not a:
                    continue
                # segnali + monitor
                check_signal(sym, a)
                monitor_trade(sym, a["price"])

            # Report :00 / :30 oppure subito dopo avvio
            now_utc = time.time()
            if report_immediato or now_utc >= next_report_ts:
                report_immediato = False

                it = datetime.now(tz=ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M")
                utc = datetime.now(tz=ZoneInfo("UTC")).strftime("%d/%m %H:%M")
                msg = f"🕒 Report {it} (Italia) | {utc} UTC\n"

                trends = {}
                for sym in ["BTC", "ETH"]:
                    a = analyze(sym)
                    if a:
                        msg += "\n" + line(sym, a["price"], a["ema20"], a["ema60"], a["vol15m"], a["avg_vol15m"])
                        trends[sym] = "🟢" if a["ema20"] > a["ema60"] else "🔴" if a["ema20"] < a["ema60"] else "⚪"
                    else:
                        msg += f"\n{sym}: Errore dati"
                        trends[sym] = "⚪"

                msg += f"\n\n{suggestion(trends['BTC'], trends['ETH'])}"
                send_telegram(msg)

                next_report_ts = next_half_hour_epoch() + 1

            time.sleep(5)

        except Exception as e:
            log(f"Loop error: {e}")
            time.sleep(10)
