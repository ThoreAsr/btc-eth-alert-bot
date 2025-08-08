import time
import requests
from datetime import datetime, timedelta

# === CONFIG ===
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"
SYMBOL_MEXC_BTC = "BTC_USDT"
SYMBOL_MEXC_ETH = "ETH_USDT"
UPDATE_INTERVAL = 1800  # 30 minuti

# === COINMARKETCAP ===
CMC_API_KEY = "e1bf46bf-1e42-4c30-8847-c011f772dcc8"
CMC_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"

# === UTILS ===
def get_price_mexc(symbol):
    try:
        url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol.replace('_', '')}"
        response = requests.get(url)
        return float(response.json()["price"])
    except:
        return None

def get_volume_cmc(symbol):
    try:
        params = {"symbol": symbol, "convert": "USDT"}
        headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
        response = requests.get(CMC_URL, params=params, headers=headers)
        data = response.json()
        return float(data["data"][symbol]["quote"]["USDT"]["volume_24h"]) / 1_000_000  # In milioni
    except:
        return None

def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, data=data)

# === MAIN LOOP ===
prices_btc = []
prices_eth = []
last_report_time = datetime.utcnow() - timedelta(seconds=UPDATE_INTERVAL)

while True:
    now = datetime.utcnow()

    btc_price = get_price_mexc(SYMBOL_MEXC_BTC)
    eth_price = get_price_mexc(SYMBOL_MEXC_ETH)

    btc_vol = get_volume_cmc("BTC")
    eth_vol = get_volume_cmc("ETH")

    if btc_price and eth_price:
        prices_btc.append(btc_price)
        prices_eth.append(eth_price)
        prices_btc = prices_btc[-200:]
        prices_eth = prices_eth[-200:]

    btc_ema20 = calculate_ema(prices_btc, 20)
    btc_ema60 = calculate_ema(prices_btc, 60)
    eth_ema20 = calculate_ema(prices_eth, 20)
    eth_ema60 = calculate_ema(prices_eth, 60)

    # === GENERA SEGNALE ===
    def signal(price, ema20, ema60):
        if None in [price, ema20, ema60]:
            return "🕐 Nessun segnale"
        if price > ema20 > ema60:
            return "🟢 Segnale LONG"
        elif price < ema20 < ema60:
            return "🔴 Segnale SHORT"
        else:
            return "⚪ Nessun segnale"

    btc_signal = signal(btc_price, btc_ema20, btc_ema60)
    eth_signal = signal(eth_price, eth_ema20, eth_ema60)

    # === INVIA REPORT OGNI 30 MIN O IN CASO DI SEGNALE ===
    if (now - last_report_time).seconds >= UPDATE_INTERVAL or "Segnale" in btc_signal or "Segnale" in eth_signal:
        last_report_time = now
        timestamp = now.strftime("%H:%M UTC")
        msg = f"🕒 *Report {timestamp}*\n\n"
        msg += f"*BTC:* {btc_price:.2f}$ | EMA20:{btc_ema20} | EMA60:{btc_ema60} | Vol:{round(btc_vol, 2)}M\n{btc_signal}\n\n"
        msg += f"*ETH:* {eth_price:.2f}$ | EMA20:{eth_ema20} | EMA60:{eth_ema60} | Vol:{round(eth_vol, 2)}M\n{eth_signal}"
        send_telegram_message(msg)

    time.sleep(30)
