import requests
import time
import numpy as np
from datetime import datetime, timedelta

# ================= CONFIGURAZIONE =================
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"  # ID del gruppo
UPDATE_INTERVAL = 60        # Controllo ogni 60 secondi
UPDATE_LEVELS_HOURS = 24    # Aggiornamento livelli dinamici ogni 24 ore

# Simboli
SYMBOL_MEXC = "BTCUSDT"
SYMBOL_MEXC_ETH = "ETHUSDT"
SYMBOL_BINANCE = "BTCUSDT"
SYMBOL_BINANCE_ETH = "ETHUSDT"

# Livelli dinamici iniziali
dynamic_levels = {
    "BTC": {"support": None, "resistance": None},
    "ETH": {"support": None, "resistance": None}
}

# ================= FUNZIONI API =================
def get_price_mexc(symbol):
    try:
        url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
        data = requests.get(url, timeout=5).json()
        return float(data["price"])
    except:
        return None

def get_volume_binance(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
        data = requests.get(url, timeout=5).json()
        return float(data["volume"])
    except:
        return 0.0

# ================= CALCOLI =================
def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    ema = np.convolve(prices, weights, mode='full')[:len(prices)]
    return round(ema[-1], 2)

# ================= ANALISI SEGNALE =================
def generate_signal(price, ema20, ema60, ema120, ema200, volume, support, resistance, asset):
    """
    Genera un segnale LONG o SHORT basato su incroci EMA + breakout + volumi
    """
    # Validazione input
    if None in [price, ema20, ema60, ema120, ema200]:
        return "⚪ Nessun segnale"

    signal = "⚪ Nessun segnale"
    strength = ""

    # Segnale LONG
    if price > ema20 and price > ema60 and price > ema120 and price > ema200:
        if volume > 5_000_000:  # soglia indicativa
            signal = "🟢 LONG"
            strength = "FORTE ✅"
        else:
            signal = "🟢 LONG"
            strength = "DEBOLE ⚠️"

    # Segnale SHORT
    elif price < ema20 and price < ema60 and price < ema120 and price < ema200:
        if volume > 5_000_000:
            signal = "🔴 SHORT"
            strength = "FORTE ✅"
        else:
            signal = "🔴 SHORT"
            strength = "DEBOLE ⚠️"

    # Controllo breakout livelli dinamici
    if resistance and price > resistance * 1.01:
        signal += " | Breakout Resistenza"
    elif support and price < support * 0.99:
        signal += " | Breakdown Supporto"

    return f"{signal} ({strength})"

# ================= TELEGRAM =================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except:
        pass

# ================= AGGIORNAMENTO LIVELLI DINAMICI =================
def update_dynamic_levels():
    btc_price = get_price_mexc(SYMBOL_MEXC)
    eth_price = get_price_mexc(SYMBOL_MEXC_ETH)
    if btc_price:
        dynamic_levels["BTC"]["support"] = round(btc_price * 0.98, 2)
        dynamic_levels["BTC"]["resistance"] = round(btc_price * 1.02, 2)
    if eth_price:
        dynamic_levels["ETH"]["support"] = round(eth_price * 0.98, 2)
        dynamic_levels["ETH"]["resistance"] = round(eth_price * 1.02, 2)
    send_telegram_message("🔄 *Livelli dinamici aggiornati*")

# ================= LOOP PRINCIPALE =================
send_telegram_message("✅ *Bot PRO+ avviato* – Prezzo MEXC, volumi Binance, 4 EMA e TP multipli")
update_dynamic_levels()

prices_btc = []
prices_eth = []
last_update = datetime.utcnow() - timedelta(hours=UPDATE_LEVELS_HOURS)

while True:
    # Aggiorna livelli dinamici ogni 24h
    if datetime.utcnow() - last_update > timedelta(hours=UPDATE_LEVELS_HOURS):
        update_dynamic_levels()
        last_update = datetime.utcnow()

    # Ottieni prezzi e volumi
    btc_price = get_price_mexc(SYMBOL_MEXC)
    eth_price = get_price_mexc(SYMBOL_MEXC_ETH)
    btc_vol = get_volume_binance(SYMBOL_BINANCE)
    eth_vol = get_volume_binance(SYMBOL_BINANCE_ETH)

    if btc_price and eth_price:
        prices_btc.append(btc_price)
        prices_eth.append(eth_price)

        prices_btc = prices_btc[-200:]
        prices_eth = prices_eth[-200:]

        # Calcola EMA
        btc_ema20 = calculate_ema(prices_btc, 20)
        btc_ema60 = calculate_ema(prices_btc, 60)
        btc_ema120 = calculate_ema(prices_btc, 120)
        btc_ema200 = calculate_ema(prices_btc, 200)

        eth_ema20 = calculate_ema(prices_eth, 20)
        eth_ema60 = calculate_ema(prices_eth, 60)
        eth_ema120 = calculate_ema(prices_eth, 120)
        eth_ema200 = calculate_ema(prices_eth, 200)

        # Genera segnali
        btc_signal = generate_signal(
            btc_price, btc_ema20, btc_ema60, btc_ema120, btc_ema200,
            btc_vol, dynamic_levels["BTC"].get("support"), dynamic_levels["BTC"].get("resistance"), "BTC"
        )
        eth_signal = generate_signal(
            eth_price, eth_ema20, eth_ema60, eth_ema120, eth_ema200,
            eth_vol, dynamic_levels["ETH"].get("support"), dynamic_levels["ETH"].get("resistance"), "ETH"
        )

        # Messaggio finale
        message = (
            f"🕒 Report {datetime.utcnow().strftime('%H:%M')} UTC\n\n"
            f"*BTC*: {btc_price}$ | EMA20:{btc_ema20} | EMA60:{btc_ema60} | EMA120:{btc_ema120} | EMA200:{btc_ema200} | Vol:{round(btc_vol/1_000_000,1)}M\n"
            f"{btc_signal}\n\n"
            f"*ETH*: {eth_price}$ | EMA20:{eth_ema20} | EMA60:{eth_ema60} | EMA120:{eth_ema120} | EMA200:{eth_ema200} | Vol:{round(eth_vol/1_000_000,1)}M\n"
            f"{eth_signal}"
        )
        send_telegram_message(message)

    time.sleep(UPDATE_INTERVAL)
