import requests
import time
import numpy as np
from datetime import datetime, timedelta

# ===============================
# CONFIGURAZIONE
# ===============================
BOT_TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"  # ID del gruppo

SYMBOL_MEXC = "BTCUSDT"
SYMBOL_MEXC_ETH = "ETHUSDT"
SYMBOL_BINANCE = "BTCUSDT"
SYMBOL_BINANCE_ETH = "ETHUSDT"

UPDATE_INTERVAL = 60       # secondi tra report
UPDATE_LEVELS_HOURS = 24   # ore per aggiornare livelli dinamici

# ===============================
# FUNZIONI UTILI
# ===============================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Errore invio messaggio: {e}")

def get_price_mexc(symbol):
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        return float(data["price"])
    except:
        return None

def get_volume_binance(symbol):
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        return float(data["quoteVolume"])
    except:
        return None

def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    return float(np.mean(prices[-period:]))

def generate_signal(price, ema20, ema60, volume, support, resistance, symbol):
    if ema20 is None or ema60 is None:
        return "Nessun segnale"

    signal = "Nessun segnale"
    emoji = "⚪"

    # Logica LONG: prezzo sopra entrambe le EMA + volumi alti
    if price > ema20 and price > ema60 and volume and volume > 1_000_000:
        signal = "LONG forte"
        emoji = "🟢"

    # Logica SHORT: prezzo sotto entrambe le EMA + volumi alti
    elif price < ema20 and price < ema60 and volume and volume > 1_000_000:
        signal = "SHORT forte"
        emoji = "🔴"

    return f"{emoji} {signal}"

# ===============================
# LOOP PRINCIPALE
# ===============================
def main():
    send_telegram_message("✅ Bot PRO+ avviato – Prezzo MEXC, volumi Binance, 2 EMA e TP multipli")

    last_update = datetime.utcnow() - timedelta(hours=UPDATE_LEVELS_HOURS)
    dynamic_levels = {"BTC": {"support": None, "resistance": None},
                      "ETH": {"support": None, "resistance": None}}

    prices_btc, prices_eth = [], []

    while True:
        # Aggiorna livelli dinamici ogni 24h
        if datetime.utcnow() - last_update > timedelta(hours=UPDATE_LEVELS_HOURS):
            send_telegram_message("🔄 Livelli dinamici aggiornati")
            last_update = datetime.utcnow()

        # Recupera prezzi e volumi
        btc_price = get_price_mexc(SYMBOL_MEXC)
        eth_price = get_price_mexc(SYMBOL_MEXC_ETH)
        btc_vol = get_volume_binance(SYMBOL_BINANCE)
        eth_vol = get_volume_binance(SYMBOL_BINANCE_ETH)

        if btc_price and eth_price:
            prices_btc.append(btc_price)
            prices_eth.append(eth_price)

            prices_btc = prices_btc[-200:]
            prices_eth = prices_eth[-200:]

            btc_ema20 = calculate_ema(prices_btc, 20)
            btc_ema60 = calculate_ema(prices_btc, 60)
            eth_ema20 = calculate_ema(prices_eth, 20)
            eth_ema60 = calculate_ema(prices_eth, 60)

            # Segnali
            btc_signal = generate_signal(btc_price, btc_ema20, btc_ema60, btc_vol,
                                         dynamic_levels["BTC"]["support"], dynamic_levels["BTC"]["resistance"], "BTC")
            eth_signal = generate_signal(eth_price, eth_ema20, eth_ema60, eth_vol,
                                         dynamic_levels["ETH"]["support"], dynamic_levels["ETH"]["resistance"], "ETH")

            # Messaggio report
            report = (
                f"🕒 Report {datetime.utcnow().strftime('%H:%M')} UTC\n\n"
                f"*BTC:* {btc_price}$ | EMA20:{btc_ema20} | EMA60:{btc_ema60} | Vol:{btc_vol}\n{btc_signal}\n\n"
                f"*ETH:* {eth_price}$ | EMA20:{eth_ema20} | EMA60:{eth_ema60} | Vol:{eth_vol}\n{eth_signal}"
            )
            send_telegram_message(report)

        time.sleep(UPDATE_INTERVAL)

# Avvia il bot
if __name__ == "__main__":
    main()
