import time
import requests
from datetime import datetime, timedelta

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "356760541"

# Livelli breakout/breakdown iniziali
LEVELS = {
    "BTC": {"breakout": [117700, 118300], "breakdown": [116800, 116300]},
    "ETH": {"breakout": [3190, 3250], "breakdown": [3120, 3070]}
}

# API MEXC prezzi e volumi
PRICE_URLS = {
    "BTC": "https://api.mexc.com/api/v3/ticker/price?symbol=BTCUSDT",
    "ETH": "https://api.mexc.com/api/v3/ticker/price?symbol=ETHUSDT"
}
VOLUME_URLS = {
    "BTC": "https://api.mexc.com/api/v3/ticker/24hr?symbol=BTCUSDT",
    "ETH": "https://api.mexc.com/api/v3/ticker/24hr?symbol=ETHUSDT"
}

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
        except Exception as e:
            print(f"Tentativo {attempt+1} fallito per {symbol}: {e}")
        time.sleep(1)
    send_telegram_message(f"⚠️ Errore nel recupero prezzo per {symbol} dopo 3 tentativi")
    return None

def get_volume(symbol: str) -> float:
    """Ottiene volume 24h per confermare breakout/breakdown"""
    headers = {"User-Agent": "Mozilla/5.0"}
    url = VOLUME_URLS[symbol]
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        data = resp.json()
        if "quoteVolume" in data:
            return float(data["quoteVolume"])
    except Exception as e:
        print(f"Errore ottenimento volume {symbol}: {e}")
    return 0

def calc_support_resistance(prices: list):
    if not prices:
        return None, None
    support = min(prices)
    resistance = max(prices)
    return support, resistance

def check_levels(symbol: str, price: float, volume: float, levels: dict, dynamic_high: dict, dynamic_low: dict):
    # Breakout fissi
    for level in levels["breakout"]:
        if price >= level:
            send_telegram_message(f"🚀 BREAKOUT {symbol}: superato {level} – prezzo attuale {price}")
            if volume > 500000000:  # soglia volume da regolare
                send_telegram_message(f"💹 Segnale LONG {symbol}: breakout confermato da volumi alti ({volume})")

    # Breakdown fissi
    for level in levels["breakdown"]:
        if price <= level:
            send_telegram_message(f"⚠️ BREAKDOWN {symbol}: sotto {level} – prezzo attuale {price}")
            if volume > 500000000:  # soglia volume da regolare
                send_telegram_message(f"🔻 Segnale SHORT {symbol}: breakdown confermato da volumi alti ({volume})")

    # Massimo dinamico
    if price > dynamic_high[symbol]:
        dynamic_high[symbol] = price
        send_telegram_message(f"📈 NUOVO MASSIMO {symbol}: {price}")

    # Minimo dinamico
    if price < dynamic_low[symbol]:
        dynamic_low[symbol] = price
        send_telegram_message(f"📉 NUOVO MINIMO {symbol}: {price}")

# --- MAIN ---
if __name__ == "__main__":
    send_telegram_message("✅ BOT ATTIVO 24/7 – Monitoraggio BTC & ETH con breakout + volumi + segnali operativi attivi.")

    dynamic_high = {"BTC": 0, "ETH": 0}
    dynamic_low = {"BTC": 999999, "ETH": 999999}
    price_history = {"BTC": [], "ETH": []}

    while True:
        now = datetime.utcnow() + timedelta(hours=2)  # Ora italiana
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

                report_msg += f"\n{symbol}: {price}\nSupporto: {support} | Resistenza: {resistance}\nVolumi 24h: {volume}\n"
            else:
                report_msg += f"\n{symbol}: Errore prezzo\n"

        send_telegram_message(report_msg)
        time.sleep(1800)  # Report ogni 30 minuti
