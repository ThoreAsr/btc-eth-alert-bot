import time
import requests

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"  # Bot token Telegram
CHAT_ID = "356760541"  # Tuo ID Telegram

# Livelli breakout/breakdown iniziali
LEVELS = {
    "BTC": {"breakout": [117700, 118300], "breakdown": [116800, 116300]},
    "ETH": {"breakout": [3190, 3250], "breakdown": [3120, 3070]}
}

# URL API prezzi (Binance)
PRICE_URLS = {
    "BTC": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
    "ETH": "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT"
}

# --- FUNZIONI ---
def send_telegram_message(message: str):
    """Invia un messaggio su Telegram"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")

def get_price(symbol: str) -> float:
    """Ottiene prezzo corrente da Binance"""
    try:
        resp = requests.get(PRICE_URLS[symbol], timeout=5)
        return float(resp.json()["price"])
    except Exception as e:
        print(f"Errore ottenimento prezzo {symbol}: {e}")
        return None

def check_levels(symbol: str, price: float, levels: dict, dynamic_high: dict, dynamic_low: dict):
    """Controlla breakout/breakdown e dinamici"""
    # Breakout fissi
    for level in levels["breakout"]:
        if price >= level:
            send_telegram_message(f"🚀 BREAKOUT {symbol}: superato {level} – prezzo attuale {price}")

    # Breakdown fissi
    for level in levels["breakdown"]:
        if price <= level:
            send_telegram_message(f"⚠️ BREAKDOWN {symbol}: sotto {level} – prezzo attuale {price}")

    # Nuovi massimi/minimi dinamici
    if price > dynamic_high[symbol]:
        dynamic_high[symbol] = price
        send_telegram_message(f"📈 NUOVO MASSIMO {symbol}: {price}")
    if price < dynamic_low[symbol]:
        dynamic_low[symbol] = price
        send_telegram_message(f"📉 NUOVO MINIMO {symbol}: {price}")

# --- MAIN LOOP ---
if __name__ == "__main__":
    # Messaggio di avvio
    send_telegram_message("✅ BOT ATTIVO – Monitoraggio BTC & ETH avviato con breakout dinamici")

    # Inizializza massimi/minimi dinamici
    dynamic_high = {"BTC": 0, "ETH": 0}
    dynamic_low = {"BTC": 999999, "ETH": 999999}

    # Loop di monitoraggio
    while True:
        for symbol in ["BTC", "ETH"]:
            price = get_price(symbol)
            if price:
                check_levels(symbol, price, LEVELS[symbol], dynamic_high, dynamic_low)
        time.sleep(30)  # Controllo ogni 30 secondi
