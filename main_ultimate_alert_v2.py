import time
import requests
from datetime import datetime, timedelta

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "356760541"

LEVELS = {
    "BTC": {"breakout": [117700, 118300], "breakdown": [116800, 116300]},
    "ETH": {"breakout": [3190, 3250], "breakdown": [3120, 3070]}
}

# Soglie volume realistiche (USDT)
VOLUME_THRESHOLDS = {"BTC": 5_000_000, "ETH": 2_000_000}

# API candele 15m MEXC
KLINE_URL = "https://api.mexc.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=60"

# Stato segnali per evitare spam
last_signal = {"BTC": None, "ETH": None}


# --- FUNZIONI ---
def send_telegram_message(message: str):
    """Invia messaggio su Telegram"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")


def get_klines(symbol: str):
    """Ottiene ultime 60 candele 15m da MEXC"""
    headers = {"User-Agent": "Mozilla/5.0"}
    url = KLINE_URL.format(symbol=symbol)
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        return resp.json()
    except Exception as e:
        print(f"Errore klines {symbol}: {e}")
        return None


def calc_ema(prices, period):
    """Calcola EMA (Exponential Moving Average)"""
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def analyze(symbol):
    """Analizza dati candele per segnali"""
    data = get_klines(symbol)
    if not data:
        send_telegram_message(f"⚠️ Errore dati {symbol}")
        return None

    closes = [float(c[4]) for c in data]  # Prezzi di chiusura
    base_volumes = [float(c[5]) for c in data]  # Volumi in asset

    # Volume in USDT = base_volume * prezzo_chiusura
    usdt_volumes = [closes[i] * base_volumes[i] for i in range(len(closes))]

    last_close = closes[-1]
    last_volume = usdt_volumes[-1]  # Volume della candela 15m in USDT

    ema20 = calc_ema(closes[-20:], 20)
    ema60 = calc_ema(closes[-60:], 60)

    return {
        "price": last_close,
        "volume": last_volume,
        "ema20": ema20,
        "ema60": ema60
    }


def check_signal(symbol, analysis, levels):
    """Controlla breakout/breakdown e invia segnali"""
    global last_signal
    price = analysis["price"]
    volume = analysis["volume"]
    ema20 = analysis["ema20"]
    ema60 = analysis["ema60"]

    vol_thresh = VOLUME_THRESHOLDS[symbol]

    # Breakout LONG
    for level in levels["breakout"]:
        if price >= level and ema20 > ema60 and volume > vol_thresh:
            if last_signal[symbol] != "LONG":
                send_telegram_message(f"🟢 LONG {symbol} | {round(price,2)}$ | Vol {round(volume/1e6,1)}M")
                last_signal[symbol] = "LONG"

    # Breakdown SHORT
    for level in levels["breakdown"]:
        if price <= level and ema20 < ema60 and volume > vol_thresh:
            if last_signal[symbol] != "SHORT":
                send_telegram_message(f"🔴 SHORT {symbol} | {round(price,2)}$ | Vol {round(volume/1e6,1)}M")
                last_signal[symbol] = "SHORT"

    # Reset segnale se neutro
    if levels["breakdown"][-1] < price < levels["breakout"][0]:
        last_signal[symbol] = None


def format_report_line(symbol, price, ema20, ema60, volume):
    """Crea riga report con colore direzione trend"""
    trend = "🟢" if ema20 > ema60 else "🔴" if ema20 < ema60 else "⚪"
    return f"{trend} {symbol}: {round(price,2)}$ | EMA20:{round(ema20,2)} | EMA60:{round(ema60,2)} | Vol:{round(volume/1e6,1)}M"


# --- MAIN ---
if __name__ == "__main__":
    send_telegram_message("✅ Bot PRO attivo – Breakout con EMA + Volumi 15m confermati (Apple Watch ready)")

    while True:
        now = datetime.utcnow() + timedelta(hours=2)
        timestamp = now.strftime("%H:%M")

        report_msg = f"🕒 Report {timestamp}\n"

        for symbol in ["BTC", "ETH"]:
            analysis = analyze(symbol)
            if analysis:
                price = analysis["price"]
                volume = analysis["volume"]
                ema20 = analysis["ema20"]
                ema60 = analysis["ema60"]

                check_signal(symbol, analysis, LEVELS[symbol])

                report_msg += f"\n{format_report_line(symbol, price, ema20, ema60, volume)}"
            else:
                report_msg += f"\n{symbol}: Errore dati"

        send_telegram_message(report_msg)
        time.sleep(1800)  # Report ogni 30 min
