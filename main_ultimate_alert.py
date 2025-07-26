import os
import time
import requests

# ===== CONFIGURAZIONE =====
TOKEN = os.getenv("Token")   # Variabile d'ambiente su Render
CHAT_ID = os.getenv("Chat_Id")

# URL API Binance per BTC e ETH
API_BTC = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"
API_ETH = "https://api.binance.com/api/v3/ticker/24hr?symbol=ETHUSDT"

# ===== FUNZIONI =====
def manda_messaggio(testo):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    dati = {"chat_id": CHAT_ID, "text": testo}
    try:
        requests.post(url, data=dati)
    except Exception as e:
        print("Errore invio messaggio:", e)

def get_dati(api_url):
    try:
        r = requests.get(api_url).json()
        prezzo = float(r["lastPrice"])
        var_percent = float(r["priceChangePercent"])
        volume = float(r["volume"])
        return prezzo, var_percent, volume
    except:
        return None, None, None

# RSI semplificato su ultimi 14 valori
def calcola_rsi(prezzi):
    if len(prezzi) < 15:
        return 50
    gains = []
    losses = []
    for i in range(1, 15):
        diff = prezzi[-i] - prezzi[-i-1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains) / 14 if gains else 0
    avg_loss = sum(losses) / 14 if losses else 1
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

# ===== VARIABILI =====
storico_btc = []
storico_eth = []

# ===== AVVISO AVVIO =====
manda_messaggio("✅ BOT AVVIATO: Alert BTC + ETH dinamici con RSI e volumi attivi 24/7.")

# ===== LOOP PRINCIPALE =====
while True:
    # ---- BTC ----
    prezzo_btc, var_btc, vol_btc = get_dati(API_BTC)
    if prezzo_btc:
        storico_btc.append(prezzo_btc)
        if len(storico_btc) > 30:
            storico_btc.pop(0)
        rsi_btc = calcola_rsi(storico_btc)

        # Livelli dinamici: breakout/breakdown 2% da ultimi prezzi
        breakout_btc = max(storico_btc) * 1.02
        breakdown_btc = min(storico_btc) * 0.98

        if prezzo_btc >= breakout_btc and rsi_btc > 70:
            manda_messaggio(f"🚀 BREAKOUT BTC: {prezzo_btc}$ | RSI {rsi_btc} | Var {var_btc}% | Volumi {vol_btc}")
        elif prezzo_btc <= breakdown_btc and rsi_btc < 30:
            manda_messaggio(f"🔻 BREAKDOWN BTC: {prezzo_btc}$ | RSI {rsi_btc} | Var {var_btc}% | Volumi {vol_btc}")

    # ---- ETH ----
    prezzo_eth, var_eth, vol_eth = get_dati(API_ETH)
    if prezzo_eth:
        storico_eth.append(prezzo_eth)
        if len(storico_eth) > 30:
            storico_eth.pop(0)
        rsi_eth = calcola_rsi(storico_eth)

        breakout_eth = max(storico_eth) * 1.02
        breakdown_eth = min(storico_eth) * 0.98

        if prezzo_eth >= breakout_eth and rsi_eth > 70:
            manda_messaggio(f"🚀 BREAKOUT ETH: {prezzo_eth}$ | RSI {rsi_eth} | Var {var_eth}% | Volumi {vol_eth}")
        elif prezzo_eth <= breakdown_eth and rsi_eth < 30:
            manda_messaggio(f"🔻 BREAKDOWN ETH: {prezzo_eth}$ | RSI {rsi_eth} | Var {var_eth}% | Volumi {vol_eth}")

    time.sleep(900)  # 15 minuti
