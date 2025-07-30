import os
import time
import requests
import traceback
import statistics

CHECK_INTERVAL = 30  # secondi tra controlli

# --- Livelli fissi da variabili d'ambiente (modificabili da Render) ---
BTC_FIXED_BREAKOUT = float(os.getenv("BTC_BREAKOUT", 118300))
BTC_FIXED_BREAKDOWN = float(os.getenv("BTC_BREAKDOWN", 117500))
ETH_FIXED_BREAKOUT = float(os.getenv("ETH_BREAKOUT", 3000))
ETH_FIXED_BREAKDOWN = float(os.getenv("ETH_BREAKDOWN", 2950))

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
    if len(prices) < 3:  # bastano 3 letture per iniziare
        return None, None
    return min(prices), max(prices)

def start_bot():
    print("=== BOT BTC/ETH AVVIATO ===")
    send_telegram_message("✅ Bot BTC/ETH operativo 24/7: alert dinamici + fissi attivati.")

    btc_prices, eth_prices = [], []
    last_alert_btc, last_alert_eth = None, None

    while True:
        try:
            btc_price = get_price("BTCUSDT")
            eth_price = get_price("ETHUSDT")

            # ----------- BTC -----------
            if btc_price:
                btc_prices.append(btc_price)
                if len(btc_prices) > 20:
                    btc_prices.pop(0)
                support_btc, resistance_btc = get_dynamic_levels(btc_prices)

                # Reset se prezzo torna neutro
                if last_alert_btc and support_btc and resistance_btc and support_btc < btc_price < resistance_btc:
                    last_alert_btc = None

                # Breakout/Breakdown dinamici
                if resistance_btc and btc_price >= resistance_btc and last_alert_btc != "up":
                    send_telegram_message(f"🚀 BTC BREAKOUT DINAMICO: {btc_price} (res {resistance_btc})")
                    last_alert_btc = "up"
                elif support_btc and btc_price <= support_btc and last_alert_btc != "down":
                    send_telegram_message(f"⚠️ BTC BREAKDOWN DINAMICO: {btc_price} (sup {support_btc})")
                    last_alert_btc = "down"

                # Breakout/Breakdown fissi
                if btc_price >= BTC_FIXED_BREAKOUT and last_alert_btc != "fixed_up":
                    send_telegram_message(f"🚀 BTC BREAKOUT FISSO: {btc_price} sopra {BTC_FIXED_BREAKOUT}")
                    last_alert_btc = "fixed_up"
                elif btc_price <= BTC_FIXED_BREAKDOWN and last_alert_btc != "fixed_down":
                    send_telegram_message(f"⚠️ BTC BREAKDOWN FISSO: {btc_price} sotto {BTC_FIXED_BREAKDOWN}")
                    last_alert_btc = "fixed_down"

            # ----------- ETH -----------
            if eth_price:
                eth_prices.append(eth_price)
                if len(eth_prices) > 20:
                    eth_prices.pop(0)
                support_eth, resistance_eth = get_dynamic_levels(eth_prices)

                if last_alert_eth and support_eth and resistance_eth and support_eth < eth_price < resistance_eth:
                    last_alert_eth = None

                if resistance_eth and eth_price >= resistance_eth and last_alert_eth != "up":
                    send_telegram_message(f"🚀 ETH BREAKOUT DINAMICO: {eth_price} (res {resistance_eth})")
                    last_alert_eth = "up"
                elif support_eth and eth_price <= support_eth and last_alert_eth != "down":
                    send_telegram_message(f"⚠️ ETH BREAKDOWN DINAMICO: {eth_price} (sup {support_eth})")
                    last_alert_eth = "down"

                if eth_price >= ETH_FIXED_BREAKOUT and last_alert_eth != "fixed_up":
                    send_telegram_message(f"🚀 ETH BREAKOUT FISSO: {eth_price} sopra {ETH_FIXED_BREAKOUT}")
                    last_alert_eth = "fixed_up"
                elif eth_price <= ETH_FIXED_BREAKDOWN and last_alert_eth != "fixed_down":
                    send_telegram_message(f"⚠️ ETH BREAKDOWN FISSO: {eth_price} sotto {ETH_FIXED_BREAKDOWN}")
                    last_alert_eth = "fixed_down"

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
