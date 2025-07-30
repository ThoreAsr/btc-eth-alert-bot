import os
import time
import requests
import traceback
import statistics

# === CONFIGURAZIONE ===
CHECK_INTERVAL = 30  # secondi tra controlli

# LIVELLI FISSI PERSONALIZZATI
BTC_FIXED_BREAKOUT = 118300.0
BTC_FIXED_BREAKDOWN = 117500.0
ETH_FIXED_BREAKOUT = 3000.0
ETH_FIXED_BREAKDOWN = 2950.0

# === FUNZIONI TELEGRAM ===
def send_telegram_message(message):
    token = os.getenv("Token")
    chat_id = os.getenv("Chat_Id")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": message}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("Errore invio Telegram:", e)

# === FUNZIONI PREZZO ===
def get_price(symbol="BTCUSDT"):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        return float(response.json()["price"])
    except:
        return None

def get_dynamic_levels(prices):
    if len(prices) < 5:
        return None, None
    support = min(prices)
    resistance = max(prices)
    return support, resistance

# === LOGICA BOT ===
def start_bot():
    print("=== BOT BTC/ETH AVVIATO ===")
    send_telegram_message("✅ Bot BTC/ETH operativo 24/7 su Render: alert dinamici + fissi attivati.")

    btc_prices = []
    eth_prices = []
    last_alert_btc = None
    last_alert_eth = None

    while True:
        try:
            # OTTIENI PREZZI
            btc_price = get_price("BTCUSDT")
            eth_price = get_price("ETHUSDT")

            # ---------------- BTC ----------------
            if btc_price:
                btc_prices.append(btc_price)
                if len(btc_prices) > 20:
                    btc_prices.pop(0)

                support_btc, resistance_btc = get_dynamic_levels(btc_prices)

                # Livelli dinamici
                if resistance_btc and btc_price >= resistance_btc and last_alert_btc != "up":
                    send_telegram_message(f"🚀 BTC BREAKOUT DINAMICO: {btc_price} (resistenza {resistance_btc})")
                    last_alert_btc = "up"
                elif support_btc and btc_price <= support_btc and last_alert_btc != "down":
                    send_telegram_message(f"⚠️ BTC BREAKDOWN DINAMICO: {btc_price} (supporto {support_btc})")
                    last_alert_btc = "down"

                # Livelli fissi
                if btc_price >= BTC_FIXED_BREAKOUT and last_alert_btc != "fixed_up":
                    send_telegram_message(f"🚀 BTC BREAKOUT FISSO: {btc_price} sopra {BTC_FIXED_BREAKOUT}")
                    last_alert_btc = "fixed_up"
                elif btc_price <= BTC_FIXED_BREAKDOWN and last_alert_btc != "fixed_down":
                    send_telegram_message(f"⚠️ BTC BREAKDOWN FISSO: {btc_price} sotto {BTC_FIXED_BREAKDOWN}")
                    last_alert_btc = "fixed_down"

            # ---------------- ETH ----------------
            if eth_price:
                eth_prices.append(eth_price)
                if len(eth_prices) > 20:
                    eth_prices.pop(0)

                support_eth, resistance_eth = get_dynamic_levels(eth_prices)

                # Livelli dinamici
                if resistance_eth and eth_price >= resistance_eth and last_alert_eth != "up":
                    send_telegram_message(f"🚀 ETH BREAKOUT DINAMICO: {eth_price} (resistenza {resistance_eth})")
                    last_alert_eth = "up"
                elif support_eth and eth_price <= support_eth and last_alert_eth != "down":
                    send_telegram_message(f"⚠️ ETH BREAKDOWN DINAMICO: {eth_price} (supporto {support_eth})")
                    last_alert_eth = "down"

                # Livelli fissi
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
    # Loop infinito che riavvia in caso di crash
    while True:
        try:
            start_bot()
        except Exception as e:
            print("Errore critico, riavvio bot:", e)
            time.sleep(5)
