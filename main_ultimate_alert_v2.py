import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"  # ID gruppo

LEVELS = {
    "BTC": {"breakout": [117700, 118300], "breakdown": [116800, 116300]},
    "ETH": {"breakout": [3190, 3250], "breakdown": [3120, 3070]},
}

# Soglie per volume della candela 15m (USDT) da MEXC
VOLUME_THRESHOLDS = {"BTC": 5_000_000, "ETH": 2_000_000}
MIN_MOVE_PCT = 0.2
TP_PCT = 1.0
SL_PCT = 0.3

KLINE_URL = "https://api.mexc.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=60"

# Stato segnali / trade / anti-spam
last_signal = {"BTC": None, "ETH": None}
active_trade = {"BTC": None, "ETH": None}
last_weak_alert = {"BTC_breakout": 0, "BTC_breakdown": 0, "ETH_breakout": 0, "ETH_breakdown": 0}
WEAK_ALERT_COOLDOWN = 600  # 10 minuti
STARTUP_MESSAGE_SENT = False

# --- LOG (facoltativo) ---
def log(msg: str):
    ts = datetime.now(tz=ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open("bot_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

# --- TELEGRAM ---
def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=7)
    except Exception as e:
        log(f"Errore Telegram: {e}")

# --- MEXC ---
def get_klines(symbol: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    url = KLINE_URL.format(symbol=symbol)
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"Errore klines {symbol}: {e}")
        return None

def calc_ema(prices, period):
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema

# --- ANALISI ---
def analyze(symbol):
    data = get_klines(symbol)
    if not data:
        send_telegram_message(f"⚠️ Errore dati {symbol}")
        return None

    closes = [float(c[4]) for c in data]
    vols_base = [float(c[5]) for c in data]
    vols_usdt = [closes[i] * vols_base[i] for i in range(len(closes))]

    last_close = closes[-1]
    last_vol15m = vols_usdt[-1]
    ema20 = calc_ema(closes[-20:], 20)
    ema60 = calc_ema(closes[-60:], 60)

    return {"price": last_close, "volume": last_vol15m, "ema20": ema20, "ema60": ema60}

# --- TRADE ---
def open_trade(symbol, direction, entry_price):
    if direction == "LONG":
        tp = entry_price * (1 + TP_PCT/100)
        sl = entry_price * (1 - SL_PCT/100)
    else:
        tp = entry_price * (1 - TP_PCT/100)
        sl = entry_price * (1 + SL_PCT/100)

    active_trade[symbol] = {"direction": direction, "entry": entry_price, "tp": tp, "sl": sl}
    send_telegram_message(
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
            send_telegram_message(f"✅ TP raggiunto LONG {symbol} a {round(tp,2)}")
            active_trade[symbol] = None
        elif price <= sl:
            send_telegram_message(f"❌ STOP colpito LONG {symbol} a {round(sl,2)}")
            active_trade[symbol] = None

    if direction == "SHORT":
        if price <= tp:
            send_telegram_message(f"✅ TP raggiunto SHORT {symbol} a {round(tp,2)}")
            active_trade[symbol] = None
        elif price >= sl:
            send_telegram_message(f"❌ STOP colpito SHORT {symbol} a {round(sl,2)}")
            active_trade[symbol] = None

# --- SEGNALI ---
def _cooldown_ok(key: str) -> bool:
    now = time.time()
    if now - last_weak_alert.get(key, 0) >= WEAK_ALERT_COOLDOWN:
        last_weak_alert[key] = now
        return True
    return False

def check_signal(symbol, analysis, levels):
    global last_signal
    p = analysis["price"]
    v = analysis["volume"]
    ema20 = analysis["ema20"]
    ema60 = analysis["ema60"]
    vol_th = VOLUME_THRESHOLDS[symbol]

    def valid_break(level, price):
        return abs((price - level) / level * 100) > MIN_MOVE_PCT

    # breakout LONG
    for lvl in levels["breakout"]:
        if p >= lvl and ema20 > ema60 and valid_break(lvl, p):
            if v > vol_th and last_signal[symbol] != "LONG":
                open_trade(symbol, "LONG", p)
                last_signal[symbol] = "LONG"
            elif v <= vol_th and _cooldown_ok(f"{symbol}_breakout"):
                send_telegram_message(f"⚠️ Breakout debole {symbol} | {round(p,2)}$ | Vol 15m {round(v/1e6,1)}M")

    # breakdown SHORT
    for lvl in levels["breakdown"]:
        if p <= lvl and ema20 < ema60 and valid_break(lvl, p):
            if v > vol_th and last_signal[symbol] != "SHORT":
                open_trade(symbol, "SHORT", p)
                last_signal[symbol] = "SHORT"
            elif v <= vol_th and _cooldown_ok(f"{symbol}_breakdown"):
                send_telegram_message(f"⚠️ Breakdown debole {symbol} | {round(p,2)}$ | Vol 15m {round(v/1e6,1)}M")

    # reset
    if levels["breakdown"][-1] < p < levels["breakout"][0]:
        last_signal[symbol] = None

# --- REPORT ---
def format_report_line(symbol, price, ema20, ema60, volume):
    trend = "🟢" if ema20 > ema60 else "🔴" if ema20 < ema60 else "⚪"
    return f"{trend} {symbol}: {round(price,2)}$ | EMA20:{round(ema20,2)} | EMA60:{round(ema60,2)} | Vol:{round(volume/1e6,1)}M"

def build_suggestion(btc_trend, eth_trend):
    if btc_trend == "🟢" and eth_trend == "🟢":
        return "Suggerimento: Preferenza LONG ✅"
    if btc_trend == "🔴" and eth_trend == "🔴":
        return "Suggerimento: Preferenza SHORT ❌"
    return "Suggerimento: Trend misto – Attendere conferma ⚠️"

def next_half_hour_epoch() -> float:
    """Prossimo :00 o :30 allineato all'orologio."""
    now = datetime.now(tz=ZoneInfo("UTC"))
    minute = now.minute
    add_min = 30 - (minute % 30)
    if add_min == 30:
        add_min = 0
    target = (now.replace(second=0, microsecond=0) + timedelta(minutes=add_min))
    return target.timestamp()

# --- MAIN ---
if __name__ == "__main__":
    global STARTUP_MESSAGE_SENT
    if not STARTUP_MESSAGE_SENT:
        send_telegram_message("✅ Bot PRO attivo – Segnali Fortissimi con TP/SL dinamici (Apple Watch ready)")
        STARTUP_MESSAGE_SENT = True

    # pianifica il primo report al prossimo :00 o :30
    next_report_ts = next_half_hour_epoch()

    while True:
        # analisi e segnali
        for sym in ["BTC", "ETH"]:
            a = analyze(sym)
            if not a:
                continue
            check_signal(sym, a, LEVELS[sym])
            monitor_trade(sym, a["price"])

        # report ogni :00 / :30
        now_utc = time.time()
        if now_utc >= next_report_ts:
            now_it_str = datetime.now(tz=ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M")
            now_utc_str = datetime.now(tz=ZoneInfo("UTC")).strftime("%d/%m %H:%M")

            report = f"🕒 Report {now_it_str} (Italia) | {now_utc_str} UTC\n"
            trends = {}

            for sym in ["BTC", "ETH"]:
                a = analyze(sym)
                if a:
                    line = format_report_line(sym, a["price"], a["ema20"], a["ema60"], a["volume"])
                    report += f"\n{line}"
                    trends[sym] = "🟢" if a["ema20"] > a["ema60"] else "🔴" if a["ema20"] < a["ema60"] else "⚪"
                else:
                    report += f"\n{sym}: Errore dati"
                    trends[sym] = "⚪"

            report += f"\n\n{build_suggestion(trends['BTC'], trends['ETH'])}"
            send_telegram_message(report)

            # prossimo :00 o :30
            next_report_ts = next_half_hour_epoch() + 1  # +1s per sicurezza

        time.sleep(5)  # polling leggero
