import requests
import time
from datetime import datetime, timedelta

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"  # <-- tuo token
CHAT_ID = "-1002181919588"  # ID del gruppo Telegram
SYMBOL_BTC = "BTCUSDT"
SYMBOL_ETH = "ETHUSDT"

# Intervalli e EMA
INTERVAL = 1800  # 30 minuti
EMA_PERIODS = [20, 60]

# URL MEXC
MEXC_PRICE_URL = "https://api.mexc.com/api/v3/ticker/price?symbol={}"
MEXC_VOLUME_URL = "https://api.mexc.com/api/v3/ticker/24hr?symbol={}"

# Variabili dinamiche
prices_btc = []
prices_eth = []
last_dynamic_update = datetime.utcnow() - timedelta(hours=24)
dynamic_levels = {"BTC": {"support": None, "resistance": None},
                  "ETH": {"support": None, "resistance": None}}

# --- FUNZIONI ---
def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print("Errore invio Telegram:", e)

def get_price(symbol):
    try:
        resp = requests.get(MEXC_PRICE_URL.format(symbol))
        return float(resp.json()['price'])
    except:
        return None

def get_volume(symbol):
    try:
        resp = requests.get(MEXC_VOLUME_URL.format(symbol))
        return float(resp.json()['volume'])
    except:
        return None

def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    weights = []
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for price in prices:
        ema = (price - ema) * multiplier + ema
        weights.append(ema)
    return round(ema, 2)

def update_dynamic_levels():
    global dynamic_levels
    if prices_btc:
        max_btc = max(prices_btc[-60:])
        min_btc = min(prices_btc[-60:])
        dynamic_levels["BTC"]["support"] = round(min_btc, 2)
        dynamic_levels["BTC"]["resistance"] = round(max_btc, 2)
    if prices_eth:
        max_eth = max(prices_eth[-60:])
        min_eth = min(prices_eth[-60:])
        dynamic_levels["ETH"]["support"] = round(min_eth, 2)
        dynamic_levels["ETH"]["resistance"] = round(max_eth, 2)

def generate_signal(price, ema20, ema60):
    if ema20 and ema60:
        if price > ema20 > ema60:
            return "LONG"
        elif price < ema20 < ema60:
            return "SHORT"
    return "NESSUN SEGNALE"

# --- MAIN LOOP ---
send_telegram_message("✅ Bot ATTIVO – Prezzo & volumi MEXC, 2 EMA e TP multipli")

while True:
    now = datetime.utcnow()

    # Aggiorna livelli dinamici ogni 24 ore
    if now - last_dynamic_update > timedelta(hours=24):
        update_dynamic_levels()
        last_dynamic_update = now
        send_telegram_message("🔄 Livelli dinamici aggiornati")

    # Recupero dati
    btc_price = get_price(SYMBOL_BTC)
    eth_price = get_price(SYMBOL_ETH)
    btc_vol = get_volume(SYMBOL_BTC)
    eth_vol = get_volume(SYMBOL_ETH)

    if btc_price and eth_price:
        prices_btc.append(btc_price)
        prices_eth.append(eth_price)

        # Mantieni ultimi 200 prezzi
        prices_btc[:] = prices_btc[-200:]
        prices_eth[:] = prices_eth[-200:]

        # Calcola EMA
        btc_ema20 = calculate_ema(prices_btc, 20)
        btc_ema60 = calculate_ema(prices_btc, 60)
        eth_ema20 = calculate_ema(prices_eth, 20)
        eth_ema60 = calculate_ema(prices_eth, 60)

        # Segnali
        btc_signal = generate_signal(btc_price, btc_ema20, btc_ema60)
        eth_signal = generate_signal(eth_price, eth_ema20, eth_ema60)

        # Messaggio
        msg = (
            f"🕒 Report {now.strftime('%H:%M')} UTC\n\n"
            f"<b>BTC:</b> {btc_price}$ | EMA20:{btc_ema20} | EMA60:{btc_ema60} | Vol:{btc_vol}M\n"
            f"{'Segnale: ' + btc_signal if btc_signal else 'Nessun segnale'}\n\n"
            f"<b>ETH:</b> {eth_price}$ | EMA20:{eth_ema20} | EMA60:{eth_ema60} | Vol:{eth_vol}M\n"
            f"{'Segnale: ' + eth_signal if eth_signal else 'Nessun segnale'}"
        )

        send_telegram_message(msg)

    # Aspetta 30 minuti
    time.sleep(INTERVAL)
