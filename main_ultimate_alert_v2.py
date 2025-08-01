import time
import requests
from datetime import datetime, timedelta

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"  # ID gruppo Bot_BTC_ETH_Famiglia

LEVELS = {
    "BTC": {"breakout": [117700, 118300], "breakdown": [116800, 116300]},
    "ETH": {"breakout": [3190, 3250], "breakdown": [3120, 3070]}
}

VOLUME_THRESHOLDS = {"BTC": 5_000_000, "ETH": 2_000_000}  # USDT
MIN_MOVE_PCT = 0.2  # % minima superamento livello
TP_PCT = 1.0        # Target +1%
SL_PCT = 0.3        # Stop -0.3%

KLINE_URL = "https://api.mexc.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=60"

# Stato segnali
last_signal = {"BTC": None, "ETH": None}
active_trade = {"BTC": None, "ETH": None}  # Salva target e stop


# --- FUNZIONI BASE ---
def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")


def get_klines(symbol: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    url = KLINE_URL.format(symbol=symbol)
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        return resp.json()
    except Exception as e:
        print(f"Errore klines {symbol}: {e}")
        return None


def calc_ema(prices, period):
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


# --- ANALISI DATI ---
def analyze(symbol):
    data = get_klines(symbol)
    if not data:
        send_telegram_message(f"⚠️ Errore dati {symbol}")
        return None

    closes = [float(c[4]) for c in data]
    base_volumes = [float(c[5]) for c in data]
    usdt_volumes = [closes[i] * base_volumes[i] for i in range(len(closes))]

    last_close = closes[-1]
    last_volume = usdt_volumes[-1]
    ema20 = calc_ema(closes[-20:], 20)
    ema60 = calc_ema(closes[-60:], 60)

    return {
        "price": last_close,
        "volume": last_volume,
        "ema20": ema20,
        "ema60": ema60
    }


# --- SEGNALI E TRADE ---
def open_trade(symbol, direction, entry_price):
    """Imposta target e stop dinamici"""
    if direction == "LONG":
        tp = entry_price * (1 + TP_PCT / 100)
        sl = entry_price * (1 - SL_PCT / 100)
    else:
        tp = entry_price * (1 - TP_PCT / 100)
        sl = entry_price * (1 + SL_PCT / 100)

    active_trade[symbol] = {
        "direction": direction,
        "entry": entry_price,
        "tp": tp,
        "sl": sl
    }

    send_telegram_message(
        f"🔥 SEGNALE FORTISSIMO {direction} {symbol}\n"
        f"Entra: {round(entry_price,2)} | Target: {round(tp,2)} | Stop: {round(sl,2)}"
    )


def monitor_trade(symbol, price):
    """Controlla se target o stop vengono colpiti"""
    trade = active_trade[symbol]
    if not trade:
        return

    direction = trade["direction"]
    tp = trade["tp"]
    sl = trade["sl"]

    # LONG
    if direction == "LONG":
        if price >= tp:
            send_telegram_message(f"✅ TP raggiunto LONG {symbol} a {round(tp,2)}")
            active_trade[symbol] = None
        elif price <= sl:
            send_telegram_message(f"❌ STOP colpito LONG {symbol} a {round(sl,2)}")
            active_trade[symbol] = None

    # SHORT
    if direction == "SHORT":
        if price <= tp:
            send_telegram_message(f"✅ TP raggiunto SHORT {symbol} a {round(tp,2)}")
            active_trade[symbol] = None
        elif price >= sl:
            send_telegram_message(f"❌ STOP colpito SHORT {symbol} a {round(sl,2)}")
            active_trade[symbol] = None


def check_signal(symbol, analysis, levels):
    global last_signal
    price = analysis["price"]
    volume = analysis["volume"]
    ema20 = analysis["ema20"]
    ema60 = analysis["ema60"]

    vol_thresh = VOLUME_THRESHOLDS[symbol]

    def valid_break(level, current_price):
        return abs((current_price - level) / level * 100) > MIN_MOVE_PCT

    # Breakout LONG
    for level in levels["breakout"]:
        if price >= level and ema20 > ema60 and valid_break(level, price):
            if volume > vol_thresh and last_signal[symbol] != "LONG":
                open_trade(symbol, "LONG", price)
                last_signal[symbol] = "LONG"
            elif volume <= vol_thresh:
                send_telegram_message(f"⚠️ Breakout debole {symbol} | {round(price,2)}$ | Vol {round(volume/1e6,1)}M")

    # Breakdown SHORT
    for level in levels["breakdown"]:
        if price <= level and ema20 < ema60 and valid_break(level, price):
            if volume > vol_thresh and last_signal[symbol] != "SHORT":
                open_trade(symbol, "SHORT", price)
                last_signal[symbol] = "SHORT"
            elif volume <= vol_thresh:
                send_telegram_message(f"⚠️ Breakdown debole {symbol} | {round(price,2)}$ | Vol {round(volume/1e6,1)}M")

    # Reset segnale se neutro
    if levels["breakdown"][-1] < price < levels["breakout"][0]:
        last_signal[symbol] = None


# --- REPORT TREND ---
def format_report_line(symbol, price, ema20, ema60, volume):
    trend = "🟢" if ema20 > ema60 else "🔴" if ema20 < ema60 else "⚪"
    return f"{trend} {symbol}: {round(price,2)}$ | EMA20:{round(ema20,2)} | EMA60:{round(ema60,2)} | Vol:{round(volume/1e6,1)}M"


def build_suggestion(btc_trend, eth_trend):
    if btc_trend == "🟢" and eth_trend == "🟢":
        return "Suggerimento: Preferenza LONG ✅"
    elif btc_trend == "🔴" and eth_trend == "🔴":
        return "Suggerimento: Preferenza SHORT ❌"
    else:
        return "Suggerimento: Trend misto – Attendere conferma ⚠️"


# --- MAIN LOOP ---
if __name__ == "__main__":
    send_telegram_message("✅ Bot PRO attivo – Segnali Fortissimi con TP/SL dinamici (Apple Watch ready)")

    while True:
        now = datetime.utcnow() + timedelta(hours=2)
        timestamp = now.strftime("%H:%M")

        report_msg = f"🕒 Report {timestamp}\n"

        trends = {}

        for symbol in ["BTC", "ETH"]:
            analysis = analyze(symbol)
            if analysis:
                price = analysis["price"]
                volume = analysis["volume"]
                ema20 = analysis["ema20"]
                ema60 = analysis["ema60"]

                # Controlla segnali
                check_signal(symbol, analysis, LEVELS[symbol])

                # Monitora eventuale trade aperto
                monitor_trade(symbol, price)

                # Aggiungi trend
                trend_emoji = "🟢" if ema20 > ema60 else "🔴" if ema20 < ema60 else "⚪"
                trends[symbol] = trend_emoji

                report_msg += f"\n{format_report_line(symbol, price, ema20, ema60, volume)}"
            else:
                report_msg += f"\n{symbol}: Errore dati"
                trends[symbol] = "⚪"

        # Aggiungi suggerimento operativo
        report_msg += f"\n\n{build_suggestion(trends['BTC'], trends['ETH'])}"

        send_telegram_message(report_msg)
        time.sleep(1800)  # Report ogni 30 min
