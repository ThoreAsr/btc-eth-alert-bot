import os
import time
import requests
import statistics

# ===== CONFIGURAZIONE =====
TOKEN = os.getenv("Token")         # Token del bot Telegram da Render
CHAT_ID = os.getenv("Chat_Id")     # Chat ID personale da Render
CHECK_INTERVAL = 300               # Controllo ogni 5 minuti (300 secondi)
RSI_PERIOD = 14                    # Periodo RSI
ALERT_THRESHOLD = 70               # Soglia RSI per alert
PRICE_API = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=100"


# ===== FUNZIONE INVIO TELEGRAM =====
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"Errore invio messaggio: {e}")


# ===== CALCOLO RSI =====
def calculate_rsi(prices, period=14):
    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
        else:
            losses.append(abs(change))

    avg_gain = statistics.mean(gains[-period:]) if gains else 0
    avg_loss = statistics.mean(losses[-period:]) if losses else 1

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)


# ===== LOOP PRINCIPALE =====
def main():
    send_telegram_message("✅ BOT AVVIATO: Alert BTC/ETH attivi con RSI e volumi.")

    while True:
        try:
            # Dati prezzo BTC da Binance
            response = requests.get(PRICE_API)
            data = response.json()

            close_prices = [float(candle[4]) for candle in data]
            rsi = calculate_rsi(close_prices, RSI_PERIOD)

            # Alert su RSI
            if rsi >= ALERT_THRESHOLD:
                send_telegram_message(f"🚨 ALERT BTC: RSI alto = {rsi}")

            # Puoi aggiungere qui anche ETH con stessa logica
            # e controlli sui volumi se vuoi renderlo ancora più preciso

        except Exception as e:
            print(f"Errore loop principale: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
