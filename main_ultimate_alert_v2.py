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

# Soglie volumi realistiche
VOLUME_THRESHOLDS = {"BTC": 100000000, "ETH": 50000000}

PRICE_URLS = {
    "BTC": "https://api.mexc.com/api/v3/ticker/price?symbol=BTCUSDT",
    "ETH": "https://api.mexc.com/api/v3/ticker/price?symbol=ETHUSDT"
}
VOLUME_URLS = {
    "BTC": "https://api.mexc.com/api/v3/ticker/24hr?symbol=BTCUSDT",
    "ETH": "https://api.mexc.com/api/v3/ticker/24hr?symbol=ETHUSDT"
}

# Stato segnali per evitare spam
last_signal = {"BTC": None, "ETH": None}

# --- FUNZIONI ---
def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")

def get_price(symbol: str) -> float:
    headers = {"User-Agent": "Mozilla/5.0"}
    url = PRICE_URLS[symbol]
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            data = resp.json()
            if "price" in data:
                return float(data["price"])
        except:
            pass
        time.sleep(1)
    send_telegram_message(f"⚠️ Errore prezzo {symbol}")
    return None

def get_volume(symbol: str) -> float:
    headers = {"User-Agent": "Mozilla/5.0"}
    url = VOLUME_URLS[symbol]
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        data = resp.json()
        if "quoteVolume" in data:
            return float(data["quoteVolume"])
    except:
        pass
    return 0

def calc_support_resistance(prices: list):
    if not prices:
        return None, None
    return min(prices), max(prices)

def check_levels(symbol, price, volume, levels, dynamic_high, dynamic_low):
    global last_signal
    vol_thresh = VOLUME_THRESHOLDS[symbol]

    # Breakout
    for level in levels["breakout"]:
        if price >= level:
            if volume > vol_thresh and last_signal[symbol] != "LONG":
                send_telegram_message(f"🟢 LONG {symbol} | {price}$ | Vol {round(volume/1e6,1)}M")
                last_signal[symbol] = "LONG"
            elif volume <= vol_thresh:
                send_telegram_message(f"⚠️ Breakout debole {symbol}: {price}$ (Vol {round(volume/1e6,1)}M)")

    # Breakdown
    for level in levels["breakdown"]:
        if price <= level:
            if volume > vol_thresh and last_signal[symbol] != "SHORT":
                send_telegram_message(f"🔴 SHORT {symbol} | {price}$ | Vol {round(volume/1e6,1)}M")
                last_signal[symbol] = "SHORT"
            elif volume <= vol_thresh:
                send_telegram_message(f"⚠️ Breakdown debole {symbol}: {price}$ (Vol {round(volume/1e6,1)}M)")

    # Reset segnali se torna neutro
    if levels["breakdown"][-1] < price < levels["breakout"][0]:
        last_signal[symbol] = None

    # Dinamici
    if price > dynamic_high[symbol]:
        dynamic_high[symbol] = price
        send_telegram_message(f"📈 Nuovo massimo {symbol}: {price}$")
    if price < dynamic_low[symbol]:
        dynamic_low[symbol] = price
        send_telegram_message(f"📉 Nuovo minimo {symbol}: {price}$")

# --- MAIN ---
if __name__ == "__main__":
    send_telegram_message("✅ Bot attivo 24/7 – BTC & ETH breakout + volumi + segnali ottimizzati Apple Watch")

    dynamic_high = {"BTC": 0, "ETH": 0}
    dynamic_low = {"BTC": 999999, "ETH": 999999}
    price_history = {"BTC": [], "ETH": []}

    while True:
        now = datetime.utcnow() + timedelta(hours=2)
        timestamp = now.strftime("%H:%M")

        report_msg = f"🕒 Report {timestamp}\n"

        for symbol in ["BTC", "ETH"]:
            price = get_price(symbol)
            volume = get_volume(symbol)

            if price:
                price_history[symbol].append(price)
                if len(price_history[symbol]) > 50:
                    price_history[symbol].pop(0)

                support, resistance = calc_support_resistance(price_history[symbol])
                check_levels(symbol, price, volume, LEVELS[symbol], dynamic_high, dynamic_low)

                report_msg += f"\n{symbol}: {price}$ | Sup: {support} | Res: {resistance} | Vol: {round(volume/1e6,1)}M"
            else:
                report_msg += f"\n{symbol}: Errore prezzo"

        send_telegram_message(report_msg)
        time.sleep(1800)
