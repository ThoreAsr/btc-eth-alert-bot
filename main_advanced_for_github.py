import requests
import time

# Token e ID del tuo bot Telegram
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "356760541"

# URL per ottenere dati reali BTC ed ETH (da Binance API)
URL_BTC = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"
URL_ETH = "https://api.binance.com/api/v3/ticker/24hr?symbol=ETHUSDT"

def manda_messaggio(testo):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    dati = {"chat_id": CHAT_ID, "text": testo}
    requests.post(url, data=dati)

def get_dati(url):
    try:
        r = requests.get(url).json()
        prezzo = float(r["lastPrice"])
        cambio = float(r["priceChangePercent"])
        volumi = float(r["volume"])
        return prezzo, cambio, volumi
    except:
        return None, None, None

def calcola_rsi(prezzo_attuale, storico_prezzi):
    # Semplice RSI basato su ultimi 14 valori
    if len(storico_prezzi) < 15:
        return 50
    gains = []
    losses = []
    for i in range(1, 15):
        diff = storico_prezzi[-i] - storico_prezzi[-i-1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains) / 14 if gains else 0
    avg_loss = sum(losses) / 14 if losses else 1
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

storico_btc = []
storico_eth = []

manda_messaggio("✅ BOT AVVIATO: Alert BTC + ETH dinamici attivi con RSI e volumi.")

while True:
    # Dati BTC
    prezzo_btc, cambio_btc, vol_btc = get_dati(URL_BTC)
    if prezzo_btc:
        storico_btc.append(prezzo_btc)
        if len(storico_btc) > 30:
            storico_btc.pop(0)
        rsi_btc = calcola_rsi(prezzo_btc, storico_btc)

        # Livelli dinamici (±0.3%)
        livello_alto_btc = prezzo_btc * 1.003
        livello_basso_btc = prezzo_btc * 0.997

        if prezzo_btc > livello_alto_btc:
            manda_messaggio(f"🚀 BREAKOUT BTC: {prezzo_btc}$ | RSI {rsi_btc} | Var. {cambio_btc}% | Volumi {vol_btc}")
        elif prezzo_btc < livello_basso_btc:
            manda_messaggio(f"🔻 BREAKDOWN BTC: {prezzo_btc}$ | RSI {rsi_btc} | Var. {cambio_btc}% | Volumi {vol_btc}")

    # Dati ETH
    prezzo_eth, cambio_eth, vol_eth = get_dati(URL_ETH)
    if prezzo_eth:
        storico_eth.append(prezzo_eth)
        if len(storico_eth) > 30:
            storico_eth.pop(0)
        rsi_eth = calcola_rsi(prezzo_eth, storico_eth)

        # Livelli dinamici (±0.3%)
        livello_alto_eth = prezzo_eth * 1.003
        livello_basso_eth = prezzo_eth * 0.997

        if prezzo_eth > livello_alto_eth:
            manda_messaggio(f"🚀 BREAKOUT ETH: {prezzo_eth}$ | RSI {rsi_eth} | Var. {cambio_eth}% | Volumi {vol_eth}")
        elif prezzo_eth < livello_basso_eth:
            manda_messaggio(f"🔻 BREAKDOWN ETH: {prezzo_eth}$ | RSI {rsi_eth} | Var. {cambio_eth}% | Volumi {vol_eth}")

    time.sleep(30)
