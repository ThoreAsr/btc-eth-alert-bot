import requests
import time
from datetime import datetime, timedelta
import numpy as np

# --- CONFIGURAZIONE ---
BOT_TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"  # <-- tuo token
CHAT_ID = "-1002181919588"  # ID gruppo famiglia
SYMBOL_BTC = "BTCUSDT"
SYMBOL_ETH = "ETHUSDT"

# Intervalli di aggiornamento
UPDATE_LEVELS_HOURS = 24  # aggiornamento supporti/resistenze
REPORT_INTERVAL = 1800  # 30 minuti in secondi

# --- FUNZIONI API MEXC ---
def get_price_mexc(symbol):
    try:
        url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
        data = requests.get(url).json()
        return float(data["price"])
    except:
        return None

def get_volume_mexc(symbol):
    try:
        url = f"https://api.mexc.com/api/v3/ticker/24hr?symbol={symbol}"
        data = requests.get(url).json()
        return float(data["quoteVolume"]) / 1_000_000  # in milioni
    except:
        return None

# --- FUNZIONI TECNICHE ---
def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    ema = np.convolve(prices, weights, mode='full')[:len(prices)]
    return ema[-1]

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    requests.post(url, data=payload)

# --- LIVELLI DINAMICI ---
dynamic_levels = {"BTC": {}, "ETH": {}}

def update_dynamic_levels():
    btc_price = get_price_mexc(SYMBOL_BTC)
    eth_price = get_price_mexc(SYMBOL_ETH)

    if btc_price:
        dynamic_levels["BTC"]["support"] = btc_price * 0.98
        dynamic_levels["BTC"]["resistance"] = btc_price * 1.02
    if eth_price:
        dynamic_levels["ETH"]["support"] = eth_price * 0.98
        dynamic_levels["ETH"]["resistance"] = eth_price * 1.02

    send_telegram_message("🔄 <b>Livelli dinamici aggiornati</b>")

# --- SEGNALI OPERATIVI ---
def generate_signal(price, ema20, ema60, support, resistance, vol):
    if None in [ema20, ema60, support, resistance, vol]:
        return "Nessun segnale"

    # Logica LONG
    if price > ema20 and price > ema60 and price > resistance and vol > 5:
        return "💚 <b>Segnale LONG forte</b>"

    # Logica SHORT
    if price < ema20 and price < ema60 and price < support and vol > 5:
        return "❤️ <b>Segnale SHORT forte</b>"

    return "Nessun segnale"

# --- LOOP PRINCIPALE ---
prices_btc = []
prices_eth = []

send_telegram_message("✅ <b>Bot PRO+ avviato – Prezzo & volumi MEXC, 2 EMA e TP multipli</b>")
update_dynamic_levels()

last_update = datetime.utcnow()
last_report_time = 0

while True:
    # Aggiorna livelli dinamici ogni 24 ore
    if datetime.utcnow() - last_update > timedelta(hours=UPDATE_LEVELS_HOURS):
        update_dynamic_levels()
        last_update = datetime.utcnow()

    # Recupera prezzi e volumi
    btc_price = get_price_mexc(SYMBOL_BTC)
    eth_price = get_price_mexc(SYMBOL_ETH)
    btc_vol = get_volume_mexc(SYMBOL_BTC)
    eth_vol = get_volume_mexc(SYMBOL_ETH)

    if btc_price and eth_price:
        prices_btc.append(btc_price)
        prices_eth.append(eth_price)

    # Mantieni solo ultimi 200 prezzi
    prices_btc = prices_btc[-200:]
    prices_eth = prices_eth[-200:]

    # Calcolo EMA
    btc_ema20 = calculate_ema(prices_btc, 20)
    btc_ema60 = calculate_ema(prices_btc, 60)
    eth_ema20 = calculate_ema(prices_eth, 20)
    eth_ema60 = calculate_ema(prices_eth, 60)

    # Genera segnali
    btc_signal = generate_signal(
        btc_price, btc_ema20, btc_ema60,
        dynamic_levels["BTC"].get("support"),
        dynamic_levels["BTC"].get("resistance"),
        btc_vol
    )

    eth_signal = generate_signal(
        eth_price, eth_ema20, eth_ema60,
        dynamic_levels["ETH"].get("support"),
        dynamic_levels["ETH"].get("resistance"),
        eth_vol
    )

    # Invio report ogni 30 min
    current_time = time.time()
    if current_time - last_report_time >= REPORT_INTERVAL:
        msg = f"🕒 <b>Report {datetime.utcnow().strftime('%H:%M')} UTC</b>\n\n"
        msg += f"<b>BTC:</b> {btc_price}$ | EMA20:{btc_ema20} | EMA60:{btc_ema60} | Vol:{btc_vol}M\n{btc_signal}\n\n"
        msg += f"<b>ETH:</b> {eth_price}$ | EMA20:{eth_ema20} | EMA60:{eth_ema60} | Vol:{eth_vol}M\n{eth_signal}"
        send_telegram_message(msg)
        last_report_time = current_time

    # Alert istantanei in caso di breakout
    if btc_price and dynamic_levels["BTC"].get("resistance") and btc_price > dynamic_levels["BTC"]["resistance"]:
        send_telegram_message(f"🚀 <b>BREAKOUT BTC!</b> Prezzo: {btc_price}$")
    elif btc_price and dynamic_levels["BTC"].get("support") and btc_price < dynamic_levels["BTC"]["support"]:
        send_telegram_message(f"⚠️ <b>BREAKDOWN BTC!</b> Prezzo: {btc_price}$")

    if eth_price and dynamic_levels["ETH"].get("resistance") and eth_price > dynamic_levels["ETH"]["resistance"]:
        send_telegram_message(f"🚀 <b>BREAKOUT ETH!</b> Prezzo: {eth_price}$")
    elif eth_price and dynamic_levels["ETH"].get("support") and eth_price < dynamic_levels["ETH"]["support"]:
        send_telegram_message(f"⚠️ <b>BREAKDOWN ETH!</b> Prezzo: {eth_price}$")

    time.sleep(30)  # Controllo ogni 30 secondi
