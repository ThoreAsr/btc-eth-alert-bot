# main_ultimate_alert_v2.py
# Bot BTC/ETH – breakout dinamici + volumi 15m con rapporto, TP/SL dinamici
# Report ogni 30 minuti (solo orario Italia). Segnali Apple-Watch friendly.

import time
import math
import requests
from datetime import datetime, timedelta

# =============== CONFIG =================

TOKEN   = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"

# Opzionale (oggi non obbligatorio). Lasciare "" se non usi conferma CMC.
CMC_API_KEY = ""   # es. "e1bf46bf-...."  (se vuoto: ignorato)

# Prezzi/volumi 15m da MEXC
KLINE_URL = "https://api.mexc.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit={limit}"

SYMBOLS = ["BTC", "ETH"]

# Livelli dinamici (massimo/minimo lookback) e sensibilità breakout
LOOKBACK_BARS   = 96           # ~24 ore su 15m
MIN_MOVE_PCT    = 0.15         # % minima oltre il livello dinamico per contare come breakout

# Volumi: soglia forza / rapporto vol/avg
VOL_AVG_BARS    = 32           # media 15m per confronto
VOL_STRONG_X    = 1.30         # >= 1.30x media => forte
VOL_WEAK_X      = 1.05         # 1.05–1.30x => debole (se <1.05x non segnaliamo)

# TP/SL dinamici
TP_PCT = 0.80                   # 0.80% target
SL_PCT = 0.35                   # 0.35% stop

# Report & antispam
REPORT_EVERY_SEC   = 30 * 60    # ogni 30 minuti
SIGNAL_COOLDOWN_S  = 10 * 60    # non ripetere lo stesso segnale per 10 minuti

# =======================================


# Stato in memoria
last_report_ts = 0
last_signal = {s: {"dir": None, "ts": 0} for s in SYMBOLS}

# Banner avvio una sola volta
STARTUP_SENT = False


# ---------- Utils ----------
def it_now():
    # Solo orario Italia (UTC+2 “estivo” come da tua richiesta)
    return datetime.utcnow() + timedelta(hours=2)

def short_ts():
    return it_now().strftime("%H:%M")

def round2(x):
    try:
        return round(float(x), 2)
    except:
        return x

def send(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=8
        )
    except Exception as e:
        print("Telegram error:", e)


# ---------- Data ----------
def get_klines(symbol: str, limit=LOOKBACK_BARS+VOL_AVG_BARS+5):
    url = KLINE_URL.format(symbol=symbol, limit=limit)
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        closes = [float(c[4]) for c in data]
        base_vol = [float(c[5]) for c in data]  # quantità (coin)
        # Convertiamo in USDT volume stimato: close * base_vol
        usdt_vol = [closes[i] * base_vol[i] for i in range(len(closes))]
        return closes, usdt_vol
    except Exception as e:
        print("MEXC error", symbol, e)
        return None, None


def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


# ---------- Analisi ----------
def analyze(symbol: str):
    closes, usdt_vol = get_klines(symbol)
    if not closes or not usdt_vol or len(closes) < LOOKBACK_BARS + VOL_AVG_BARS + 2:
        return None

    price = closes[-1]
    ema20 = ema(closes[-20:], 20)
    ema60 = ema(closes[-60:], 60)

    # vol 15m corrente e media
    vol15  = usdt_vol[-1]
    avg15  = sum(usdt_vol[-VOL_AVG_BARS:]) / VOL_AVG_BARS
    ratio  = vol15 / avg15 if avg15 > 0 else 0.0

    # livelli dinamici (escludo barra corrente)
    dyn_high = max(closes[-(LOOKBACK_BARS+1):-1])
    dyn_low  = min(closes[-(LOOKBACK_BARS+1):-1])

    # trend con EMA
    trend_up = ema20 is not None and ema60 is not None and ema20 > ema60
    trend_dn = ema20 is not None and ema60 is not None and ema20 < ema60

    return {
        "price": price,
        "ema20": ema20,
        "ema60": ema60,
        "vol15": vol15,
        "avg15": avg15,
        "ratio": ratio,
        "dyn_high": dyn_high,
        "dyn_low": dyn_low,
        "trend_up": trend_up,
        "trend_dn": trend_dn,
    }


def strong_or_weak(ratio):
    if ratio >= VOL_STRONG_X:
        return "strong"
    if ratio >= VOL_WEAK_X:
        return "weak"
    return "none"


def check_breakouts(sym: str, a: dict):
    """Ritorna un dict con eventuale segnale e tipo."""
    if not a:
        return None

    p  = a["price"]
    hi = a["dyn_high"]
    lo = a["dyn_low"]
    up = a["trend_up"]
    dn = a["trend_dn"]
    ratio = a["ratio"]

    signal = None
    # Breakout LONG sopra il massimo dinamico
    if p >= hi * (1 + MIN_MOVE_PCT/100.0) and up:
        kind = strong_or_weak(ratio)
        if kind != "none":
            signal = {"dir": "LONG", "kind": kind, "price": p}

    # Breakdown SHORT sotto il minimo dinamico
    if p <= lo * (1 - MIN_MOVE_PCT/100.0) and dn:
        kind = strong_or_weak(ratio)
        if kind != "none":
            signal = {"dir": "SHORT", "kind": kind, "price": p}

    return signal


def format_report_line(sym: str, a: dict):
    dot = "🟢" if a["ema20"] > a["ema60"] else "🔴" if a["ema20"] < a["ema60"] else "🟡"
    # Volumi in M
    v_now  = f"{a['vol15']/1e6:.1f}M"
    v_avg  = f"{a['avg15']/1e6:.1f}M"
    ratio  = f"{a['ratio']:.2f}x"
    return (
        f"{dot} <b>{sym}</b>: {round2(a['price'])}$ | "
        f"EMA20:{round2(a['ema20'])} | EMA60:{round2(a['ema60'])} | "
        f"Vol15m:{v_now} (avg:{v_avg} | {ratio})"
    )


def send_signal(sym: str, sig: dict, a: dict):
    """Invia breakout debole o ENTRA forte con TP/SL."""
    now_ts = time.time()
    prev = last_signal[sym]

    # Antispam: evita lo stesso segnale entro il cooldown
    if prev["dir"] == sig["dir"] and (now_ts - prev["ts"] < SIGNAL_COOLDOWN_S):
        return

    last_signal[sym] = {"dir": sig["dir"], "ts": now_ts}

    # Messaggi
    if sig["kind"] == "weak":
        label = "Breakout debole" if sig["dir"] == "LONG" else "Breakdown debole"
        send(
            f"⚠️ <b>{label} {sym}</b> | {round2(sig['price'])}$ | "
            f"Vol15m {a['vol15']/1e6:.1f}M ({a['ratio']:.2f}x)"
        )
    else:
        # Forte => ENTRA + TP/SL
        entry = sig["price"]
        if sig["dir"] == "LONG":
            tp = entry * (1 + TP_PCT/100.0)
            sl = entry * (1 - SL_PCT/100.0)
        else:
            tp = entry * (1 - TP_PCT/100.0)
            sl = entry * (1 + SL_PCT/100.0)

        send(
            "🔥 <b>ENTRA {dir} {sym}</b>\n"
            "Prezzo: {p}\nTarget: {tp}\nStop: {sl}".format(
                dir=sig["dir"], sym=sym, p=round2(entry), tp=round2(tp), sl=round2(sl)
            )
        )


# ---------- MAIN ----------
def main():
    global STARTUP_SENT, last_report_ts

    if not STARTUP_SENT:
        send("✅ Bot attivo – Segnali con <b>conferma volumi</b> (solo orario Italia)")
        STARTUP_SENT = True

    while True:
        try:
            # REPORT ogni 30 minuti
            now = time.time()
            if now - last_report_ts >= REPORT_EVERY_SEC:
                last_report_ts = now

                lines = []
                analy = {}

                for s in SYMBOLS:
                    a = analyze(s)
                    analy[s] = a
                    if a:
                        lines.append(format_report_line(s, a))
                    else:
                        lines.append(f"🟡 <b>{s}</b>: dati non disponibili")

                # Suggerimento semplice: se entrambi up -> LONG; entrambi dn -> SHORT; altrimenti neutro
                def tflag(x): 
                    return 1 if analy[x] and analy[x]["trend_up"] else (-1 if analy[x] and analy[x]["trend_dn"] else 0)
                tsum = tflag("BTC") + tflag("ETH")
                if tsum == 2:
                    suggestion = "Suggerimento: Preferenza LONG ✅"
                elif tsum == -2:
                    suggestion = "Suggerimento: Preferenza SHORT ❌"
                else:
                    suggestion = "Suggerimento: Trend misto – Attendere conferma ⚠️"

                report = (
                    f"🕒 Report {short_ts()} (Italia)\n\n" +
                    "\n".join(lines) +
                    f"\n\n{suggestion}"
                )
                send(report)

            # Segnali in tempo quasi-reale (loop leggero)
            for s in SYMBOLS:
                a = analyze(s)
                if not a:
                    continue
                sig = check_breakouts(s, a)
                if sig:
                    send_signal(s, sig, a)

            time.sleep(30)  # frequenza controllo segnale

        except Exception as e:
            print("Loop error:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
