import time
import requests
from datetime import datetime, timedelta

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"  # Bot Telegram
CHAT_ID = "356760541"  # ID Telegram

# Livelli breakout/breakdown iniziali (fissi)
LEVELS = {
    "BTC": {"breakout": [117700, 118300], "breakdown": [116800, 116300]},
    "ETH": {"breakout": [3190, 3250], "breakdown": [3120, 3070]}
}

# API MEXC per prezzi
PRICE_URLS = {
    "BTC": "https://api.mexc.com/api/v3/ticker/price?symbol=BTCUSDT",
    "ETH": "https://api.mexc.com/api/v3/ticker/price?symbol=ETHUSDT"
}

# --- FUNZIONI ---
def send_telegram_message(message: str):
    """Invia messaggio su Telegram"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")

def get_price(symbol: str) -> float:
    """Ottiene prezzo corrente da MEXC con retry"""
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

def calc_support_resistance(prices: list):
    """Calcola supporto e resistenza base su ultimi prezzi"""
    if not prices:
        return None, None
    support = min(prices)
    resistance = max(prices)
    return support, resistance

def check_levels(symbol: str, price: float, levels: dict, dynamic_high: dict, dynamic_low: dict):
    """Controlla breakout, breakdown e massimi/minimi dinamici"""
    # Breakout fissi
    for level in levels["breakout"]:
        if price >= level:
            send_telegram_message(f"🚀 BREAKOUT {symbol}: superato {level} – prezzo attuale {price}")

    # Breakdown fissi
    for level in levels["breakdown"]:
        if price <= level:
            send_telegram_message(f"⚠️ BREAKDOWN {symbol}: sotto {level} – prezzo attuale {price}")

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
    send_telegram_message("✅ BOT ATTIVO 24/7 – Monitoraggio BTC & ETH (MEXC) con breakout dinamici + fissi attivati.")

    dynamic_high = {"BTC": 0, "ETH": 0}
    dynamic_low = {"BTC": 999999, "ETH": 999999}
    price_history = {"BTC": [], "ETH": []}

    while True:
        now = datetime.utcnow() + timedelta(hours=2)  # Ora italiana
        timestamp = now.strftime("%H:%M")

        report_msg = f"🕒 Report {timestamp}\n"

        for symbol in ["BTC", "ETH"]:
            price = get_price(symbol)
            if price:
                price_history[symbol].append(price)
                if len(price_history[symbol]) > 50:
                    price_history[symbol].pop(0)

                support, resistance = calc_support_resistance(price_history[symbol])
                check_levels(symbol, price, LEVELS[symbol], dynamic_high, dynamic_low)

                report_msg += f"\n{symbol}: {price}\nSupporto: {support} | Resistenza: {resistance}\n"
            else:
                report_msg += f"\n{symbol}: Errore prezzo\n"

        send_telegram_message(report_msg)
        time.sleep(1800)  # Report ogni 30 minuti
