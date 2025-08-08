import requests
import time
from datetime import datetime, timedelta

# === CONFIG ===
TELEGRAM_TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
TELEGRAM_CHAT_ID = "-1002181919588"
CMC_API_KEY = "e1bf46bf-1e42-4c30-8847-c011f772dcc8"

SYMBOL_BTC = "BTC"
SYMBOL_ETH = "ETH"

UPDATE_INTERVAL_MINUTES = 30
prices_btc = []
prices_eth = []

# === FUNZIONI TELEGRAM ===
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=data)
    except:
        pass

# === FUNZIONI MEXC ===
def get_price_mexc(symbol):
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}USDT"
    try:
        response = requests.get(url).json()
        return float(response["price"])
    except:
        return None

# === FUNZIONI VOLUME GLOBALI COINMARKETCAP ===
def get_volume_cmc(symbol):
    url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol}"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    try:
        response = requests.get(url, headers=headers).json()
        return response["data"][symbol]["quote"]["USD"]["volume_24h"]
    except:
        return None

# === CALCOLO EMA ===
def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)

# === GENERA MESSAGGIO ===
def build_report(price_btc, ema20_btc, ema60_btc, vol_btc, price_eth, ema20_eth, ema60_eth, vol_eth):
    msg = f"🕓 Report {datetime.utcnow().strftime('%H:%M')} UTC\n\n"

    msg += f"**BTC**: {price_btc}$ | EMA20:{ema20_btc} | EMA60:{ema60_btc} | Vol:{round(vol_btc/1_000_000, 2)}M\n"
    msg += interpret_signal(price_btc, ema20_btc, ema60_btc)

    msg += f"\n\n**ETH**: {price_eth}$ | EMA20:{ema20_eth} | EMA60:{ema60_eth} | Vol:{round(vol_eth/1_000_000, 2)}M\n"
    msg += interpret_signal(price_eth, ema20_eth, ema60_eth)

    return msg

def interpret_signal(price, ema20, ema60):
    if not ema20 or not ema60:
        return "Nessun segnale"
    if price > ema20 > ema60:
        return "📈 Segnale BUY"
    elif price < ema20 < ema60:
        return "📉 Segnale SELL"
    else:
        return "Nessun segnale"

# === MAIN LOOP ===
last_sent = None

while True:
    btc_price = get_price_mexc(SYMBOL_BTC)
    eth_price = get_price_mexc(SYMBOL_ETH)
    btc_vol = get_volume_cmc(SYMBOL_BTC)
    eth_vol = get_volume_cmc(SYMBOL_ETH)

    if btc_price:
        prices_btc.append(btc_price)
        prices_btc = prices_btc[-200:]

    if eth_price:
        prices_eth.append(eth_price)
        prices_eth = prices_eth[-200:]

    btc_ema20 = calculate_ema(prices_btc, 20)
    btc_ema60 = calculate_ema(prices_btc, 60)
    eth_ema20 = calculate_ema(prices_eth, 20)
    eth_ema60 = calculate_ema(prices_eth, 60)

    now = datetime.utcnow()
    if not last_sent or (now - last_sent) >= timedelta(minutes=UPDATE_INTERVAL_MINUTES):
        msg = build_report(btc_price, btc_ema20, btc_ema60, btc_vol,
                           eth_price, eth_ema20, eth_ema60, eth_vol)
        send_telegram_message(msg)
        last_sent = now

    time.sleep(30)
