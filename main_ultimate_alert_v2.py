import requests
import time
from datetime import datetime, timedelta
import numpy as np

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"  # Token bot Telegram
CHAT_ID = "-1002181919588"  # ID gruppo Telegram
SYMBOL_MEXC = "BTCUSDT"
SYMBOL_MEXC_ETH = "ETHUSDT"
SYMBOL_BINANCE = "BTCUSDT"
SYMBOL_BINANCE_ETH = "ETHUSDT"
INTERVAL = 900  # 15 minuti
UPDATE_LEVELS_HOURS = 24  # Aggiorna livelli dinamici ogni 24 ore

# --- FUNZIONI UTILI ---
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Errore Telegram: {e}")

def get_price_mexc(symbol):
    try:
        url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url).json()
        return float(r["price"])
    except:
        return None

def get_volume_binance(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
        r = requests.get(url).json()
        return float(r["quoteVolume"])
    except:
        return None

def calculate_ema(prices, period):
    return np.round(np.mean(prices[-period:]), 2) if len(prices) >= period else None

# --- CALCOLO LIVELLI DINAMICI ---
dynamic_levels = {"BTC": {}, "ETH": {}}

def update_dynamic_levels():
    btc_price = get_price_mexc(SYMBOL_MEXC)
    eth_price = get_price_mexc(SYMBOL_MEXC_ETH)

    if btc_price and eth_price:
        dynamic_levels["BTC"]["support"] = btc_price * 0.98
        dynamic_levels["BTC"]["resistance"] = btc_price * 1.02
        dynamic_levels["ETH"]["support"] = eth_price * 0.98
        dynamic_levels["ETH"]["resistance"] = eth_price * 1.02

        send_telegram_message("🔄 Livelli dinamici aggiornati")

# --- LOGICA SEGNALI ---
def generate_signal(price, ema20, ema60, ema120, ema200, volume, support, resistance, asset):
    signal = ""
    strength = ""

    if price > ema20 and price > ema60 and price > ema120 and price > ema200:
        signal = "LONG"
        strength = "forte" if price > resistance else "medio"
    elif price < ema20 and price < ema60 and price < ema120 and price < ema200:
        signal = "SHORT"
        strength = "forte" if price < support else "medio"
    else:
        signal = "NEUTRO"
        strength = "debole"

    emoji = "🟢" if signal == "LONG" else "🔴" if signal == "SHORT" else "⚪"

    return f"{emoji} {signal} {asset} ({strength})\nPrezzo: {price}$ | Vol: {volume/1_000_000:.1f}M\nSup: {support:.2f} | Res: {resistance:.2f}"

# --- LOOP PRINCIPALE ---
send_telegram_message("✅ Bot PRO+ avviato – Prezzo MEXC, volumi Binance, 4 EMA e TP multipli")

last_update = datetime.utcnow() - timedelta(hours=UPDATE_LEVELS_HOURS)

prices_btc = []
prices_eth = []

while True:
    # Aggiornamento livelli dinamici ogni 24 ore
    if datetime.utcnow() - last_update > timedelta(hours=UPDATE_LEVELS_HOURS):
        update_dynamic_levels()
        last_update = datetime.utcnow()

    # Recupero prezzi e volumi
    btc_price = get_price_mexc(SYMBOL_MEXC)
    eth_price = get_price_mexc(SYMBOL_MEXC_ETH)
    btc_vol = get_volume_binance(SYMBOL_BINANCE)
    eth_vol = get_volume_binance(SYMBOL_BINANCE_ETH)

    if btc_price and eth_price:
        prices_btc.append(btc_price)
        prices_eth.append(eth_price)

        # Mantieni solo ultimi 200 prezzi
        prices_btc = prices_btc[-200:]
        prices_eth = prices_eth[-200:]

        # Calcolo EMA
        btc_ema20 = calculate_ema(prices_btc, 20)
        btc_ema60 = calculate_ema(prices_btc, 60)
        btc_ema120 = calculate_ema(prices_btc, 120)
        btc_ema200 = calculate_ema(prices_btc, 200)

        eth_ema20 = calculate_ema(prices_eth, 20)
        eth_ema60 = calculate_ema(prices_eth, 60)
        eth_ema120 = calculate_ema(prices_eth, 120)
        eth_ema200 = calculate_ema(prices_eth, 200)

        # Segnali
        btc_signal = generate_signal(btc_price, btc_ema20, btc_ema60, btc_ema120, btc_ema200,
                                     btc_vol, dynamic_levels["BTC"].get("support", btc_price*0.98),
                                     dynamic_levels["BTC"].get("resistance", btc_price*1.02), "BTC")
        eth_signal = generate_signal(eth_price, eth_ema20, eth_ema60, eth_ema120, eth_ema200,
                                     eth_vol, dynamic_levels["ETH"].get("support", eth_price*0.98),
                                     dynamic_levels["ETH"].get("resistance", eth_price*1.02), "ETH")

        # Invio report
        send_telegram_message(f"🕒 Report {datetime.utcnow().strftime('%H:%M')}\n\n{btc_signal}\n\n{eth_signal}")

    time.sleep(INTERVAL)
