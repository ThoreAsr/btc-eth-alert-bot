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

# --- Storage iniziale con dati storici per partenza immediata
prices_btc = []
prices_eth = []

# === FUNZIONI TELEGRAM ===
def send_msg(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"})

# === FUNZIONI API ===
def get_price_mexc(symbol):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}USDT")
        return float(r.json()["price"])
    except:
        return None

def get_volume_cmc(symbol):
    try:
        url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol}"
        headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
        r = requests.get(url, headers=headers).json()
        return r["data"][symbol]["quote"]["USD"]["volume_24h"]
    except:
        return None

# === CALCOLO EMA ===
def ema(values, n):
    if len(values) < n:
        return None
    k = 2 / (n + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return round(e, 2)

# === COSTRUZIONE REPORT ===
def signal_text(price, e20, e60):
    if e20 is None or e60 is None:
        return "⚪ Nessun segnale"
    if price > e20 > e60:
        return "🟢 <b>BUY</b>"
    if price < e20 < e60:
        return "🔴 <b>SELL</b>"
    return "⚪ Nessun segnale"

def build_report(btc_p, b20, b60, bvol, eth_p, e20, e60, evol):
    now = datetime.utcnow().strftime('%H:%M UTC')
    msg = (
        f"🕓 Report <b>{now}</b>\n\n"
        f"<b>BTC</b>: {btc_p}$ | EMA20:{b20} | EMA60:{b60} | Vol:{round(bvol/1_000_000,1)}M\n"
        f"{signal_text(btc_p, b20, b60)}\n\n"
        f"<b>ETH</b>: {eth_p}$ | EMA20:{e20} | EMA60:{e60} | Vol:{round(evol/1_000_000,1)}M\n"
        f"{signal_text(eth_p, e20, e60)}"
    )
    return msg

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

    b20 = ema(prices_btc, 20)
    b60 = ema(prices_btc, 60)
    e20 = ema(prices_eth, 20)
    e60 = ema(prices_eth, 60)

    now = datetime.utcnow()
    if not last_sent or (now - last_sent) >= timedelta(minutes=UPDATE_INTERVAL_MINUTES):
        report = build_report(btc_price, b20, b60, btc_vol, eth_price, e20, e60, eth_vol)
        send_msg(report)
        last_sent = now

    time.sleep(30)
