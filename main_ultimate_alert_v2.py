import time
import requests
from datetime import datetime, timedelta
import statistics

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"  # Gruppo famiglia

# Parametri dinamici
VOLUME_THRESHOLDS = {"BTC": 5_000_000, "ETH": 2_000_000}  # USDT
MIN_MOVE_PCT = 0.2
TP1_PCT = 0.8
TP2_PCT = 1.5
SL_PCT = 0.3

# API
MEXC_KLINE = "https://api.mexc.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=100"
BINANCE_KLINE = "https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=100"

# Stato segnali e livelli
last_signal = {"BTC": None, "ETH": None}
active_trade = {"BTC": None, "ETH": None}
dynamic_levels = {"BTC": None, "ETH": None}
log_file = "trade_log.txt"

# --- FUNZIONI BASE ---
def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")


def get_klines_mexc(symbol: str):
    """Prezzi da MEXC"""
    try:
        resp = requests.get(MEXC_KLINE.format(symbol=symbol), timeout=5)
        return resp.json()
    except Exception as e:
        print(f"Errore MEXC {symbol}: {e}")
        return None


def get_klines_binance(symbol: str):
    """Volumi da Binance"""
    try:
        resp = requests.get(BINANCE_KLINE.format(symbol=symbol), timeout=5)
        return resp.json()
    except Exception as e:
        print(f"Errore Binance {symbol}: {e}")
        return None


def calc_ema(prices, period):
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def log_trade(entry):
    """Scrive nel log su Render"""
    with open(log_file, "a") as f:
        f.write(f"{datetime.utcnow()} - {entry}\n")


# --- LIVELLI DINAMICI ---
def update_dynamic_levels():
    """Calcola livelli breakout/breakdown dalle ultime 24h"""
    for symbol in ["BTC", "ETH"]:
        data = get_klines_mexc(symbol)
        if not data:
            continue

        closes = [float(c[4]) for c in data]
        high = max(closes[-96:])  # 24h su 15m
        low = min(closes[-96:])

        breakout_levels = [round(high * 0.997, 2), round(high, 2)]
        breakdown_levels = [round(low * 1.003, 2), round(low, 2)]

        dynamic_levels[symbol] = {
            "breakout": breakout_levels,
            "breakdown": breakdown_levels
        }

    send_telegram_message("🔄 Livelli dinamici aggiornati")


# --- ANALISI DATI ---
def analyze(symbol):
    """Prezzo da MEXC, volume da Binance"""
    mexc_data = get_klines_mexc(symbol)
    binance_data = get_klines_binance(symbol)
    if not mexc_data or not binance_data:
        return None

    closes = [float(c[4]) for c in mexc_data]
    binance_volumes = [float(c[5]) * float(c[4]) for c in binance_data]

    price = closes[-1]
    volume = binance_volumes[-1]

    ema20 = calc_ema(closes[-20:], 20)
    ema60 = calc_ema(closes[-60:], 60)
    ema100 = calc_ema(closes[-100:], 100)
    ema200 = calc_ema(closes[-100:], 200)

    return {
        "price": price,
        "volume": volume,
        "ema20": ema20,
        "ema60": ema60,
        "ema100": ema100,
        "ema200": ema200
    }


# --- FORZA TREND ---
def trend_strength(ema20, ema60, ema100, ema200):
    if ema20 > ema60 > ema100 > ema200:
        return "FORTISSIMO"
    elif ema20 > ema60:
        return "MEDIO"
    else:
        return "DEBOLE"


# --- GESTIONE TRADE ---
def open_trade(symbol, direction, entry_price):
    tp1 = entry_price * (1 + TP1_PCT / 100) if direction == "LONG" else entry_price * (1 - TP1_PCT / 100)
    tp2 = entry_price * (1 + TP2_PCT / 100) if direction == "LONG" else entry_price * (1 - TP2_PCT / 100)
    sl = entry_price * (1 - SL_PCT / 100) if direction == "LONG" else entry_price * (1 + SL_PCT / 100)

    active_trade[symbol] = {
        "direction": direction,
        "entry": entry_price,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "tp1_hit": False
    }

    send_telegram_message(
        f"🔥 {direction} {symbol} | Entra: {round(entry_price,2)}\nTP1: {round(tp1,2)} | TP2: {round(tp2,2)} | SL: {round(sl,2)}"
    )
    log_trade(f"OPEN {direction} {symbol} at {entry_price}")


def monitor_trade(symbol, price):
    trade = active_trade[symbol]
    if not trade:
        return

    direction = trade["direction"]

    # LONG
    if direction == "LONG":
        if not trade["tp1_hit"] and price >= trade["tp1"]:
            send_telegram_message(f"✅ TP1 raggiunto LONG {symbol} a {round(trade['tp1'],2)}")
            trade["tp1_hit"] = True
            log_trade(f"TP1 HIT LONG {symbol} at {trade['tp1']}")

        if price >= trade["tp2"]:
            send_telegram_message(f"✅ TP2 raggiunto LONG {symbol} a {round(trade['tp2'],2)} – Trade chiuso")
            active_trade[symbol] = None
            log_trade(f"TP2 HIT LONG {symbol}")

        elif price <= trade["sl"]:
            send_telegram_message(f"❌ STOP colpito LONG {symbol} a {round(trade['sl'],2)}")
            active_trade[symbol] = None
            log_trade(f"STOP HIT LONG {symbol}")

    # SHORT
    if direction == "SHORT":
        if not trade["tp1_hit"] and price <= trade["tp1"]:
            send_telegram_message(f"✅ TP1 raggiunto SHORT {symbol} a {round(trade['tp1'],2)}")
            trade["tp1_hit"] = True
            log_trade(f"TP1 HIT SHORT {symbol} at {trade['tp1']}")

        if price <= trade["tp2"]:
            send_telegram_message(f"✅ TP2 raggiunto SHORT {symbol} a {round(trade['tp2'],2)} – Trade chiuso")
            active_trade[symbol] = None
            log_trade(f"TP2 HIT SHORT {symbol}")

        elif price >= trade["sl"]:
            send_telegram_message(f"❌ STOP colpito SHORT {symbol} a {round(trade['sl'],2)}")
            active_trade[symbol] = None
            log_trade(f"STOP HIT SHORT {symbol}")


# --- CHECK SEGNALI ---
def check_signal(symbol, analysis):
    global last_signal
    price = analysis["price"]
    volume = analysis["volume"]
    ema20 = analysis["ema20"]
    ema60 = analysis["ema60"]
    ema100 = analysis["ema100"]
    ema200 = analysis["ema200"]

    # forza trend
    strength = trend_strength(ema20, ema60, ema100, ema200)

    # livelli dinamici
    levels = dynamic_levels[symbol]
    if not levels:
        return

    vol_thresh = VOLUME_THRESHOLDS[symbol]

    # Breakout LONG
    for level in levels["breakout"]:
        if price >= level and ema20 > ema60:
            if volume > vol_thresh and last_signal[symbol] != "LONG":
                if strength == "FORTISSIMO":
                    open_trade(symbol, "LONG", price)
                elif strength == "MEDIO":
                    send_telegram_message(f"🟡 Segnale MEDIO LONG {symbol} | {round(price,2)}$ | Vol {round(volume/1e6,1)}M")
                else:
                    send_telegram_message(f"⚠️ Segnale DEBOLE LONG {symbol} – No trade")
                last_signal[symbol] = "LONG"

    # Breakdown SHORT
    for level in levels["breakdown"]:
        if price <= level and ema20 < ema60:
            if volume > vol_thresh and last_signal[symbol] != "SHORT":
                if strength == "FORTISSIMO":
                    open_trade(symbol, "SHORT", price)
                elif strength == "MEDIO":
                    send_telegram_message(f"🟡 Segnale MEDIO SHORT {symbol} | {round(price,2)}$ | Vol {round(volume/1e6,1)}M")
                else:
                    send_telegram_message(f"⚠️ Segnale DEBOLE SHORT {symbol} – No trade")
                last_signal[symbol] = "SHORT"

    # Reset segnale
    if levels["breakdown"][-1] < price < levels["breakout"][0]:
        last_signal[symbol] = None


# --- REPORT ---
def format_report_line(symbol, price, ema20, ema60, volume):
    trend = "🟢" if ema20 > ema60 else "🔴" if ema20 < ema60 else "⚪"
    return f"{trend} {symbol}: {round(price,2)}$ | EMA20:{round(ema20,2)} | EMA60:{round(ema60,2)} | Vol:{round(volume/1e6,1)}M"


def build_suggestion(btc_trend, eth_trend):
    if btc_trend == "🟢" and eth_trend == "🟢":
        return "Suggerimento: Preferenza LONG ✅"
    elif btc_trend == "🔴" and eth_trend == "🔴":
        return "Suggerimento: Preferenza SHORT ❌"
    else:
        return "Suggerimento: Trend misto – Attendere conferma ⚠️"


# --- MAIN ---
if __name__ == "__main__":
    send_telegram_message("✅ Bot PRO+ avviato – Prezzo MEXC, volumi Binance, 4 EMA e TP multipli")

    update_dynamic_levels()  # Aggiorna subito i livelli al primo avvio
    last_update = datetime.utcnow()

    while True:
        # Aggiorna livelli ogni 24h
        if datetime.utcnow() - last_update > timedelta(hours=24):
            update_dynamic_levels()
            last_update = datetime.utcnow()

        now = datetime.utcnow() + timedelta(hours=2)
        timestamp = now.strftime("%H:%M")

        report_msg = f"🕒 Report {timestamp}\n"

        trends = {}

        for symbol in ["BTC", "ETH"]:
            analysis = analyze(symbol)
            if analysis:
                price = analysis["price"]
                volume = analysis["volume"]
                ema20 = analysis["ema20"]
                ema60 = analysis["ema60"]
                ema100 = analysis["ema100"]
                ema200 = analysis["ema200"]

                check_signal(symbol, analysis)
                monitor_trade(symbol, price)

                trend_emoji = "🟢" if ema20 > ema60 else "🔴" if ema20 < ema60 else "⚪"
                trends[symbol] = trend_emoji

                report_msg += f"\n{format_report_line(symbol, price, ema20, ema60, volume)}"
            else:
                report_msg += f"\n{symbol}: Errore dati"
                trends[symbol] = "⚪"

        report_msg += f"\n\n{build_suggestion(trends['BTC'], trends['ETH'])}"
        send_telegram_message(report_msg)

        time.sleep(1800)  # ogni 30 minuti
