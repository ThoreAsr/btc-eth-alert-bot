import os
import time
import requests
import traceback

CHECK_INTERVAL = 30  # secondi tra controlli

def send_telegram_message(message):
    token = os.getenv("Token")
    chat_id = os.getenv("Chat_Id")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": message}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("Errore invio Telegram:", e)

def get_price(symbol="BTCUSDT"):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        return float(response.json()["price"])
    except:
        return None

def get_dynamic_levels(prices):
    if len(prices) < 3:
        return None, None
    return min(prices), max(prices)

def monitor_symbol(symbol, prices, last_alert):
    price = get_price(symbol)
    if price:
        prices.append(price)
        if len(prices) > 20:
            prices.pop(0)

        support, resistance = get_dynamic_levels(prices)

        # Reset alert se rientra nel range
        if last_alert and support and resistance and support < price < resistance:
            last_alert = None

        # Breakout dinamico
        if resistance and price >= resistance and last_alert != "up":
            send_telegram_message(f"🚀 {symbol} BREAKOUT: {price} (nuova resistenza {resistance})")
            last_alert = "up"

        # Breakdown dinamico
        elif support and price <= support and last_alert != "down":
            send_telegram_message(f"⚠️ {symbol} BREAKDOWN: {price} (nuovo supporto {support})")
            last_alert = "down"

    return last_alert

def start_bot():
    print("=== BOT BTC/ETH AVVIATO ===")
    send_telegram_message("✅ Bot BTC/ETH operativo 24/7: breakout e breakdown automatici da 70.000 ai massimi!")

    btc_prices, eth_prices = [], []
    last_alert_btc, last_alert_eth = None, None

    while True:
        try:
            # Monitor BTC
            last_alert_btc = monitor_symbol("BTCUSDT", btc_prices, last_alert_btc)

            # Monitor ETH
            last_alert_eth = monitor_symbol("ETHUSDT", eth_prices, last_alert_eth)

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print("Errore nel ciclo principale:", e)
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    while True:
        try:
            start_bot()
        except Exception as e:
            print("Errore critico, riavvio bot:", e)
            time.sleep(5)
