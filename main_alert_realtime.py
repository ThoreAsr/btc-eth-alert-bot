import os
import time
import requests
import datetime

# Leggi token e chat ID dalle variabili ambiente
TOKEN = os.getenv("Token")
CHAT_ID = os.getenv("Chat_Id")

# URL API Telegram
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

# Funzione per inviare messaggi al gruppo
def send_telegram_message(message):
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(TELEGRAM_URL, data=data)
    except Exception as e:
        print(f"Errore invio messaggio: {e}")

# Funzione per ottenere prezzi BTC ed ETH
def get_prices():
    try:
        btc = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT").json()
        eth = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT").json()
        return float(btc['price']), float(eth['price'])
    except:
        return None, None

# Parametri di monitoraggio dinamico
btc_prev = None
eth_prev = None
btc_breakout_threshold = 80   # differenza in USD per considerare breakout
eth_breakout_threshold = 5    # differenza in USD per considerare breakout

send_telegram_message("✅ BOT AVVIATO: Monitoraggio reale BTC + ETH attivo con breakout dinamici!")

while True:
    btc_price, eth_price = get_prices()

    if btc_price and eth_price:
        now = datetime.datetime.now().strftime("%H:%M:%S")

        # Controllo breakout BTC
        if btc_prev and abs(btc_price - btc_prev) >= btc_breakout_threshold:
            direction = "↑ breakout rialzista" if btc_price > btc_prev else "↓ breakdown ribassista"
            send_telegram_message(f"⚡ <b>BTC ALERT {direction}</b>\nPrezzo attuale: {btc_price} USDT\nOra: {now}")

        # Controllo breakout ETH
        if eth_prev and abs(eth_price - eth_prev) >= eth_breakout_threshold:
            direction = "↑ breakout rialzista" if eth_price > eth_prev else "↓ breakdown ribassista"
            send_telegram_message(f"⚡ <b>ETH ALERT {direction}</b>\nPrezzo attuale: {eth_price} USDT\nOra: {now}")

        # Aggiorna prezzi precedenti
        btc_prev = btc_price
        eth_prev = eth_price

    # Controllo ogni 30 secondi
    time.sleep(30)
