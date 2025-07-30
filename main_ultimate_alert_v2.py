import os
import time
import requests
import traceback
import statistics

# === CONFIGURAZIONE ===
CHECK_INTERVAL = 30  # secondi tra controlli

# Funzione per inviare messaggi su Telegram
def send_telegram_message(message):
    token = os.getenv("Token")
    chat_id = os.getenv("Chat_Id")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": message}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("Errore invio Telegram:", e)

# Funzione per ottenere prezzo da Binance
def get_price(symbol="BTCUSDT"):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        return float(response.json()["price"])
    except:
        return None

# Funzione per calcolare livelli dinamici da ultime chiusure
def get_dynamic_levels(prices):
    if len(prices) < 5:
        return None, None
    avg = statistics.mean(prices)
    support = min(prices)
    resistance = max(prices)
    return support, resistance

def start_bot():
    print("=== BOT BTC/ETH AVVIATO SU RENDER ===")
    send_telegram_message("✅ Bot BTC/ETH avviato e operativo 24/7 su Render!")

    btc_prices = []
    eth_prices = []
    last_alert_btc = None
    last_alert_eth = None

    while True:
        try:
            # Ottieni prezzi live
            btc_price = get_price("BTCUSDT")
            eth_price = get_price("ETHUSDT")

            if btc_price:
                btc_prices.append(btc_price)
                if len(btc_prices) > 20:
                    btc_prices.pop(0)
                support_btc, resistance_btc = get_dynamic_levels(btc_prices)

                # Controllo breakout BTC
                if resistance_btc and btc_price >= resistance_btc and last_alert_btc != "up":
                    send_telegram_message(f"🚀 BTC BREAKOUT: {btc_price} (resistenza {resistance_btc})")
                    last_alert_btc = "up"
                elif support_btc and btc_price <= support_btc and last_alert_btc != "down":
                    send_telegram_message(f"⚠️ BTC BREAKDOWN: {btc_price} (supporto {support_btc})")
                    last_alert_btc = "down"

            if eth_price:
                eth_prices.append(eth_price)
                if len(eth_prices) > 20:
                    eth_prices.pop(0)
                support_eth, resistance_eth = get_dynamic_levels(eth_prices)

                # Controllo breakout ETH
                if resistance_eth and eth_price >= resistance_eth and last_alert_eth != "up":
                    send_telegram_message(f"🚀 ETH BREAKOUT: {eth_price} (resistenza {resistance_eth})")
                    last_alert_eth = "up"
                elif support_eth and eth_price <= support_eth and last_alert_eth != "down":
                    send_telegram_message(f"⚠️ ETH BREAKDOWN: {eth_price} (supporto {support_eth})")
                    last_alert_eth = "down"

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print("Errore nel ciclo principale:", e)
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    start_bot()
