import os
import time
import requests

# Legge TOKEN e CHAT_ID del gruppo dalle variabili ambiente
TOKEN = os.getenv("Token")
CHAT_ID = os.getenv("Chat_Id")

# Soglie dinamiche per breakout/breakdown
BREAKOUT_THRESHOLD = 0.8   # rottura forte
BREAKDOWN_THRESHOLD = -0.8 # rottura forte verso il basso

# Funzione invio messaggi
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"Errore invio messaggio: {e}")

# Funzione per ottenere prezzo e RSI
def get_price_and_rsi(symbol):
    try:
        url_price = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        url_klines = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=5m&limit=14"
        
        # Prezzo attuale
        price = float(requests.get(url_price).json()["price"])

        # Calcolo RSI (semplice)
        data = requests.get(url_klines).json()
        closes = [float(c[4]) for c in data]
        gains = [closes[i] - closes[i-1] for i in range(1, len(closes)) if closes[i] > closes[i-1]]
        losses = [closes[i-1] - closes[i] for i in range(1, len(closes)) if closes[i] < closes[i-1]]

        avg_gain = sum(gains)/14 if gains else 0.01
        avg_loss = sum(losses)/14 if losses else 0.01
        rs = avg_gain / avg_loss
        rsi = 100 - (100/(1+rs))

        return price, round(rsi, 2)
    except:
        return None, None

# Funzione analisi e invio alert
def check_alert(symbol):
    price, rsi = get_price_and_rsi(symbol)
    if price is None or rsi is None:
        return

    # Condizioni breakout/breakdown reali
    if rsi > 70:
        send_telegram(f"🚀 <b>BREAKOUT {symbol}</b>\nPrezzo: {price} USDT\nRSI: {rsi}")
    elif rsi < 30:
        send_telegram(f"⚠️ <b>BREAKDOWN {symbol}</b>\nPrezzo: {price} USDT\nRSI: {rsi}")

# Avviso di avvio
send_telegram("✅ BOT ATTIVO: Monitoraggio BTC/ETH con RSI e volumi in tempo reale.")

# Loop principale
while True:
    for coin in ["BTC", "ETH"]:
        check_alert(coin)
    time.sleep(30)  # Controllo ogni 30 secondi
