import requests
import time
from datetime import datetime, timedelta
import numpy as np

# === CONFIG ===
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"
SYMBOL_BTC = "bitcoin"
SYMBOL_ETH = "ethereum"
UPDATE_INTERVAL = 1800  # 30 minuti

# === EMA ===
def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    return float(np.round(np.mean(prices[-period:]), 2))

# === GET PRICE from MEXC ===
def get_price_mexc(symbol):
    try:
        pair = "BTCUSDT" if symbol == SYMBOL_BTC else "ETHUSDT"
        url = f"https://api.mexc.com/api/v3/ticker/price?symbol={pair}"
        return float(requests.get(url).json()['price'])
    except:
        return None

# === GET GLOBAL VOLUME from CoinMarketCap ===
CMC_API_KEY = "e1bf46bf-1e42-4c30-8847-c011f772dcc8"
HEADERS = {"X-CMC_PRO_API_KEY": CMC_API_KEY}

def get_volume_cmc(symbol):
    try:
        url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}"
        data = requests.get(url, headers=HEADERS).json()
        volume = data['data'][symbol.upper()]['quote']['USD']['volume_24h']
        return float(np.round(volume / 1_000_000, 2))  # in milioni
    except:
        return None

# === SEND TO TELEGRAM ===
def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data)
    except:
        pass

# === SIGNAL LOGIC ===
def generate_signal(price, ema20, ema60):
    if None in [price, ema20, ema60]:
        return "Nessun segnale", "⚪"
    if price > ema20 > ema60:
        return "Preferenza LONG", "🟢"
    elif price < ema20 < ema60:
        return "Preferenza SHORT", "🔴"
    elif price > ema20 and price < ema60:
        return "Breakout debole", "⚠"
    else:
        return "Trend misto - Attendere conferma", "⚠"

# === MAIN LOOP ===
btc_prices = []
eth_prices = []
next_update = time.time()

while True:
    now = datetime.utcnow()
    time_str = now.strftime("%H:%M UTC")

    btc = get_price_mexc(SYMBOL_BTC)
    eth = get_price_mexc(SYMBOL_ETH)

    vol_btc = get_volume_cmc(SYMBOL_BTC)
    vol_eth = get_volume_cmc(SYMBOL_ETH)

    if btc: btc_prices.append(btc)
    if eth: eth_prices.append(eth)
    btc_prices = btc_prices[-60:]
    eth_prices = eth_prices[-60:]

    ema_btc_20 = calculate_ema(btc_prices, 20)
    ema_btc_60 = calculate_ema(btc_prices, 60)
    ema_eth_20 = calculate_ema(eth_prices, 20)
    ema_eth_60 = calculate_ema(eth_prices, 60)

    sig_btc, icon_btc = generate_signal(btc, ema_btc_20, ema_btc_60)
    sig_eth, icon_eth = generate_signal(eth, ema_eth_20, ema_eth_60)

    msg = f"\u23f0 *Report {time_str}*\n\n"
    msg += f"*BTC:* {btc}$ | EMA20:{ema_btc_20} | EMA60:{ema_btc_60} | Vol:{vol_btc}M\n{icon_btc} {sig_btc}\n\n"
    msg += f"*ETH:* {eth}$ | EMA20:{ema_eth_20} | EMA60:{ema_eth_60} | Vol:{vol_eth}M\n{icon_eth} {sig_eth}"

    # invio ogni 30 minuti oppure se breakout
    if time.time() >= next_update or "Breakout" in sig_btc or "Breakout" in sig_eth:
        send_message(msg)
        next_update = time.time() + UPDATE_INTERVAL

    time.sleep(60)
