import requests
import numpy as np
from datetime import datetime, timedelta
import time

# === CONFIGURAZIONE ===
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"  # Token del tuo bot
CHAT_ID = "-1002181919588"  # Gruppo famiglia
SYMBOL_MEXC = "BTCUSDT"
SYMBOL_MEXC_ETH = "ETHUSDT"
SYMBOL_BINANCE = "BTCUSDT"
SYMBOL_BINANCE_ETH = "ETHUSDT"

UPDATE_INTERVAL = 60  # secondi
UPDATE_LEVELS_HOURS = 24  # ogni quanto aggiornare i livelli dinamici

# === VARIABILI GLOBALI ===
dynamic_levels = {"BTC": {}, "ETH": {}}
last_update = datetime.utcnow() - timedelta(hours=UPDATE_LEVELS_HOURS)

prices_btc = []
prices_eth = []

# === FUNZIONI API ===
def get_price_mexc(symbol):
    try:
        url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url, timeout=5)
        return float(r.json().get("price"))
    except:
        return None

def get_volume_binance(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
        r = requests.get(url, timeout=5)
        return float(r.json().get("volume"))
    except:
        return 0.0

# === CALCOLO EMA ===
def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    a = np.convolve(prices, weights, mode='full')[:len(prices)]
    a[:period] = a[period]
    return round(a[-1], 2)

# === AGGIORNAMENTO LIVELLI DINAMICI ===
def update_dynamic_levels():
    global dynamic_levels
    btc_price = get_price_mexc(SYMBOL_MEXC)
    eth_price = get_price_mexc(SYMBOL_MEXC_ETH)
    if btc_price and eth_price:
        dynamic_levels["BTC"] = {
            "support": btc_price * 0.98,
            "resistance": btc_price * 1.02
        }
        dynamic_levels["ETH"] = {
            "support": eth_price * 0.98,
            "resistance": eth_price * 1.02
        }
        send_telegram_message("♻️ Livelli dinamici aggiornati")

# === GENERA SEGNALE ===
def generate_signal(price, ema20, ema60, ema120, ema200, vol, support, resistance, coin):
    if not all([ema20, ema60, ema120, ema200]):
        return "Nessun segnale"

    if price > ema20 > ema60 > ema120 > ema200 and vol > 5_000_000:
        return f"🟢 Segnale LONG forte {coin}"
    elif price < ema20 < ema60 < ema120 < ema200 and vol > 5_000_000:
        return f"🔴 Segnale SHORT forte {coin}"
    else:
        return "Nessun segnale"

# === INVIO MESSAGGI TELEGRAM ===
def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, json=payload)
    except:
        pass

# === AVVIO BOT ===
send_telegram_message("✅ Bot PRO+ avviato – Prezzo MEXC, volumi Binance, 4 EMA e TP multipli")

# === LOOP PRINCIPALE ===
while True:
    # Aggiorna livelli dinamici ogni 24 ore
    if datetime.utcnow() - last_update > timedelta(hours=UPDATE_LEVELS_HOURS):
        update_dynamic_levels()
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

        # Calcolo EMA BTC
        btc_ema20 = calculate_ema(prices_btc, 20)
        btc_ema60 = calculate_ema(prices_btc, 60)
        btc_ema120 = calculate_ema(prices_btc, 120)
        btc_ema200 = calculate_ema(prices_btc, 200)

        # Calcolo EMA ETH
        eth_ema20 = calculate_ema(prices_eth, 20)
        eth_ema60 = calculate_ema(prices_eth, 60)
        eth_ema120 = calculate_ema(prices_eth, 120)
        eth_ema200 = calculate_ema(prices_eth, 200)

        # Segnali
        btc_signal = generate_signal(btc_price, btc_ema20, btc_ema60, btc_ema120, btc_ema200,
                                     btc_vol, dynamic_levels["BTC"].get("support"),
                                     dynamic_levels["BTC"].get("resistance"), "BTC")
        eth_signal = generate_signal(eth_price, eth_ema20, eth_ema60, eth_ema120, eth_ema200,
                                     eth_vol, dynamic_levels["ETH"].get("support"),
                                     dynamic_levels["ETH"].get("resistance"), "ETH")

        # Messaggio report
        msg = (
            f"🕒 Report {datetime.utcnow().strftime('%H:%M')} UTC\n\n"
            f"BTC: {btc_price}$ | EMA20:{btc_ema20} | EMA60:{btc_ema60} | EMA120:{btc_ema120} | EMA200:{btc_ema200} | Vol:{btc_vol/1_000_000:.1f}M\n"
            f"{btc_signal}\n\n"
            f"ETH: {eth_price}$ | EMA20:{eth_ema20} | EMA60:{eth_ema60} | EMA120:{eth_ema120} | EMA200:{eth_ema200} | Vol:{eth_vol/1_000_000:.1f}M\n"
            f"{eth_signal}"
        )

        send_telegram_message(msg)

    time.sleep(UPDATE_INTERVAL)
