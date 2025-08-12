import os
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # per gestire fusi orari

# === LIBRERIE PER GRAFICI ===
import io
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

# --- CONFIGURAZIONE ---
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"  # ID gruppo Bot_BTC_ETH_Famiglia

LEVELS = {
    "BTC": {"breakout": [117700, 118300], "breakdown": [116800, 116300]},
    "ETH": {"breakout": [3190, 3250],    "breakdown": [3120, 3070]}
}

VOLUME_THRESHOLDS = {"BTC": 5_000_000, "ETH": 2_000_000}  # USDT nominali
MIN_MOVE_PCT = 0.2   # % minima di superamento livello (residuo della tua logica)
# --- Nuovi parametri robustezza ---
BUFFER_PCT      = 0.0005  # 0.05%: chiusura oltre livello per conferma
RETEST_TOL_PCT  = 0.0002  # 0.02%: tolleranza di retest sul livello
ATR_PERIOD      = 14
ATR_SL_MULT     = 1.2
ATR_TP_MULT     = 2.0
MIN_RR          = 1.5     # R/R minimo
BE_TRIGGER_PCT  = 0.004   # +0.4% a favore
BE_WINDOW_CAND  = 2       # entro 2 candele da apertura

KLINE_URL = "https://api.mexc.com/api/v3/klines?symbol={symbol}USDT&interval=15m&limit=120"

# Stato segnali
last_signal  = {"BTC": None, "ETH": None}
active_trade = {"BTC": None, "ETH": None}  # Salva target e stop e metadata

# Startup flag per evitare messaggi ripetuti a ogni riavvio
STARTUP_FLAG = "/tmp/bot_startup_flag.txt"
STARTUP_COOLDOWN_SEC = 12 * 3600  # 12 ore


# --- UTILITY TELEGRAM ---
def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")


def send_startup_once():
    """Invia il messaggio iniziale solo una volta ogni 12 ore."""
    try:
        if os.path.exists(STARTUP_FLAG):
            with open(STARTUP_FLAG, "r") as f:
                ts = float((f.read() or "0").strip())
            if time.time() - ts < STARTUP_COOLDOWN_SEC:
                return
        send_telegram_message("✅ Bot PRO attivo – Segnali con ATR, Buffer/Retest e Break-even (Apple Watch ready)")
        with open(STARTUP_FLAG, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        print("Startup message skipped:", e)


def get_klines(symbol: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    url = KLINE_URL.format(symbol=symbol)
    try:
        resp = requests.get(url, headers=headers, timeout=7)
        return resp.json()
    except Exception as e:
        print(f"Errore klines {symbol}: {e}")
        return None


def calc_ema(prices, period):
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def build_df(symbol):
    """
    Restituisce DataFrame 15m con OHLCV e indicatori base + ATR.
    Tollerante: supporta sia klines con 12 campi (standard MEXC) sia con 8 campi.
    Non crascia se l'API risponde con errori/limiti.
    """
    data = get_klines(symbol)
    # Sanity check: data deve essere lista di liste
    if not isinstance(data, list) or (len(data) and not isinstance(data[0], (list, tuple))):
        print(f"[WARN] Risposta inattesa MEXC per {symbol}: {str(data)[:120]}")
        send_telegram_message(f"⚠️ Dati {symbol} temporaneamente non disponibili (API). Riprovo…")
        return None
    if not data:
        print(f"[WARN] Nessun dato kline per {symbol}")
        return None

    # Normalizza le righe in un formato coerente
    rows = []
    for r in data:
        # Formato 12 campi MEXC classico:
        # [open_time, open, high, low, close, volume, close_time, quote_vol,
        #  trades, taker_buy_base, taker_buy_quote, ignore]
        if len(r) >= 12:
            open_time, open_, high, low, close, volume, close_time, quote_vol, trades, tb_base, tb_quote, *_ = r
        # Formato “ridotto” 8 campi (alcuni edge case dell’API):
        # [open_time, open, high, low, close, volume, close_time, quote_vol]
        elif len(r) >= 8:
            open_time, open_, high, low, close, volume, close_time, quote_vol = r[:8]
            trades = 0
            tb_base = 0.0
            tb_quote = 0.0
        else:
            # Riga corrotta: salto
            continue

        rows.append({
            "open_time":   pd.to_datetime(int(open_time), unit="ms"),
            "open":        float(open_),
            "high":        float(high),
            "low":         float(low),
            "close":       float(close),
            "volume":      float(volume),
            "close_time":  pd.to_datetime(int(close_time), unit="ms"),
            "quote_vol":   float(quote_vol) if quote_vol is not None else 0.0,
            "trades":      int(trades) if trades is not None else 0,
            "tb_base":     float(tb_base),
            "tb_quote":    float(tb_quote),
        })

    if not rows:
        print(f"[WARN] Tutte le righe scartate per {symbol}")
        return None

    df = pd.DataFrame(rows).sort_values("close_time").reset_index(drop=True)

    # --- ATR (14)
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs()
    ], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean().fillna(method="bfill")

    # --- MACD (12,26,9)
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]

    # --- KDJ (9,3,3)
    low_min = df["low"].rolling(window=9, min_periods=9).min()
    high_max = df["high"].rolling(window=9, min_periods=9).max()
    rsv = (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan) * 100
    df["K"] = rsv.ewm(com=2, adjust=False).mean()
    df["D"] = df["K"].ewm(com=2, adjust=False).mean()
    df["J"] = 3 * df["K"] - 2 * df["D"]

    return df



# === GRAFICO + NOTIFICA ottimizzata ===
def build_chart_for(symbol, entry, tp, sl):
    df = build_df(symbol)
    if df is None:
        raise RuntimeError("Dati klines non disponibili")

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11,8), sharex=True,
                                        gridspec_kw={'height_ratios':[3,1,1]})
    # Prezzo
    ax1.plot(df["close_time"], df["close"], label=f"{symbol}/USDT")
    ax1.grid(True, linewidth=0.4)

    # Linee ben differenziate
    ax1.axhline(entry, color="#16a34a", linestyle="--",      linewidth=2.2, label="Entrata")  # verde
    ax1.axhline(tp,    color="#f59e0b", linestyle=(0,(9,4)), linewidth=2.2, label="Target")   # arancione
    ax1.axhline(sl,    color="#ef4444", linestyle=(0,(3,3)), linewidth=2.2, label="Stop")     # rosso

    # Etichette
    def annotate_hline(y, text, color):
        ax1.text(df["close_time"].iloc[-1], y, f"  {text}", color=color,
                 va="center", fontsize=10, bbox=dict(facecolor="white", alpha=0.7, edgecolor=color))
    annotate_hline(entry, f"Entrata {round(entry,2)}", "#16a34a")
    annotate_hline(tp,    f"Target {round(tp,2)}",     "#f59e0b")
    annotate_hline(sl,    f"Stop {round(sl,2)}",       "#ef4444")

    ax1.set_ylabel("USDT")
    ax1.legend(loc="upper left")

    # MACD istogramma verde/rosso
    colors = np.where(df["MACD_HIST"]>=0, "#16a34a", "#ef4444")
    ax2.bar(df["close_time"], df["MACD_HIST"], color=colors, label="Hist")
    ax2.plot(df["close_time"], df["MACD"], label="MACD")
    ax2.plot(df["close_time"], df["MACD_SIGNAL"], label="Signal")
    ax2.grid(True, linewidth=0.4)
    ax2.legend(loc="upper left")

    # KDJ
    ax3.plot(df["close_time"], df["K"], label="K")
    ax3.plot(df["close_time"], df["D"], label="D")
    ax3.plot(df["close_time"], df["J"], label="J")
    ax3.grid(True, linewidth=0.4)
    ax3.legend(loc="upper left")

    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    plt.xticks(rotation=45)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=220, bbox_inches="tight")
    plt.close(fig); buf.seek(0)
    return buf


def notify_signal(symbol, direction, entry, tp, sl):
    title = f"🚨 {direction} {symbol} 15m | Ingresso {round(entry,2)}"
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": title}, timeout=5
        )
    except Exception as e:
        print("Errore invio titolo notifica:", e)

    body = (
        f"🎯 Target: {round(tp,2)}   🛑 Stop: {round(sl,2)}\n"
        f"⏱️ TF: 15m   📊 Vol: auto\n"
        f"Entra solo se sei operativo."
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": body}, timeout=5
        )
    except Exception as e:
        print("Errore invio corpo notifica:", e)

    try:
        chart = build_chart_for(symbol, entry, tp, sl)
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": "📸 Grafico 15m con MACD & KDJ"},
            files={"photo": ("chart.png", chart.getvalue())},
            timeout=15
        )
    except Exception as e:
        print("Errore invio grafico:", e)


# --- ANALISI DATI BASE (per report) ---
def analyze(symbol):
    df = build_df(symbol)
    if df is None:
        send_telegram_message(f"⚠️ Errore dati {symbol}")
        return None

    closes = df["close"].tolist()
    base_volumes = df["volume"].tolist()
    usdt_volumes = [closes[i] * base_volumes[i] for i in range(len(closes))]

    last_close = closes[-1]
    last_volume = usdt_volumes[-1]
    ema20 = calc_ema(closes[-20:], 20)
    ema60 = calc_ema(closes[-60:], 60)
    atr14 = df["ATR"].iloc[-1]

    return {
        "price": last_close,
        "volume": last_volume,
        "ema20": ema20,
        "ema60": ema60,
        "atr":  atr14
    }


# --- TRADE MANAGEMENT ---
def open_trade(symbol, direction, entry_price, atr):
    """ATR-based TP/SL + R/R minimo + metadata per break-even."""
    # Calcolo SL/TP dinamici con ATR
    if direction == "LONG":
        sl = entry_price - ATR_SL_MULT * atr
        tp = entry_price + ATR_TP_MULT * atr
        risk = entry_price - sl
        reward = tp - entry_price
    else:
        sl = entry_price + ATR_SL_MULT * atr
        tp = entry_price - ATR_TP_MULT * atr
        risk = sl - entry_price
        reward = entry_price - tp

    rr = reward / max(risk, 1e-9)
    if rr < MIN_RR:
        send_telegram_message(f"⏭️ {symbol} {direction}: R/R {rr:.2f} < {MIN_RR}, segnale saltato")
        return

    active_trade[symbol] = {
        "direction": direction,
        "entry": entry_price,
        "tp": tp,
        "sl": sl,
        "opened_at": datetime.now(tz=ZoneInfo("UTC")),  # per BE
        "moved_to_be": False
    }

    notify_signal(symbol, direction, entry_price, tp, sl)


def monitor_trade(symbol, price):
    """Target/Stop + Break-even (+0,4% entro 2 candele)."""
    trade = active_trade[symbol]
    if not trade:
        return

    direction = trade["direction"]
    tp = trade["tp"]
    sl = trade["sl"]
    entry = trade["entry"]

    # Break-even window
    if not trade["moved_to_be"]:
        elapsed = datetime.now(tz=ZoneInfo("UTC")) - trade["opened_at"]
        within_window = elapsed <= timedelta(minutes=15*BE_WINDOW_CAND)
        if direction == "LONG" and within_window and price >= entry * (1 + BE_TRIGGER_PCT):
            trade["sl"] = entry
            trade["moved_to_be"] = True
            send_telegram_message(f"🛡️ BE attivato LONG {symbol}: SL spostato a {round(entry,2)}")
        if direction == "SHORT" and within_window and price <= entry * (1 - BE_TRIGGER_PCT):
            trade["sl"] = entry
            trade["moved_to_be"] = True
            send_telegram_message(f"🛡️ BE attivato SHORT {symbol}: SL spostato a {round(entry,2)}")

    # Gestione esiti
    if direction == "LONG":
        if price >= tp:
            send_telegram_message(f"✅ TP raggiunto LONG {symbol} a {round(tp,2)}")
            active_trade[symbol] = None
        elif price <= trade["sl"]:
            send_telegram_message(f"❌ STOP colpito LONG {symbol} a {round(trade['sl'],2)}")
            active_trade[symbol] = None
    else:
        if price <= tp:
            send_telegram_message(f"✅ TP raggiunto SHORT {symbol} a {round(tp,2)}")
            active_trade[symbol] = None
        elif price >= trade["sl"]:
            send_telegram_message(f"❌ STOP colpito SHORT {symbol} a {round(trade['sl'],2)}")
            active_trade[symbol] = None


def check_signal(symbol, analysis, levels):
    """Conferma a chiusura con BUFFER + logica retest. Usa ATR in open_trade."""
    global last_signal
    df = build_df(symbol)
    if df is None:
        return

    price = analysis["price"]
    volume = analysis["volume"]
    ema20 = analysis["ema20"]
    ema60 = analysis["ema60"]
    atr14 = analysis["atr"]
    vol_thresh = VOLUME_THRESHOLDS[symbol]

    def valid_break(level, current_price):
        return abs((current_price - level) / level * 100) > MIN_MOVE_PCT

    last = df.iloc[-1]           # ultima candela CHIUSA
    prev = df.iloc[-2]

    # Helper: condizioni di buffer e retest su breakout/breakdown
    def breakout_ok(level):
        buf = level * (1 + BUFFER_PCT)
        retest_tol = level * (1 + RETEST_TOL_PCT)
        # (A) chiusura sopra buffer
        cond_a = last["close"] > buf and prev["close"] <= buf
        # (B) retest: candela attuale ha fatto low <= livello (tolleranza) ma chiude sopra buffer
        cond_b = (last["low"] <= retest_tol) and (last["close"] > buf)
        return cond_a or cond_b

    def breakdown_ok(level):
        buf = level * (1 - BUFFER_PCT)
        retest_tol = level * (1 - RETEST_TOL_PCT)
        cond_a = last["close"] < buf and prev["close"] >= buf
        cond_b = (last["high"] >= retest_tol) and (last["close"] < buf)
        return cond_a or cond_b

    # --- Breakout LONG
    for level in levels["breakout"]:
        if price >= level and ema20 > ema60 and valid_break(level, price) and breakout_ok(level):
            if volume > vol_thresh and last_signal[symbol] != "LONG":
                open_trade(symbol, "LONG", float(last["close"]), atr14)
                last_signal[symbol] = "LONG"
            elif volume <= vol_thresh:
                send_telegram_message(f"⚠️ Breakout debole {symbol} | {round(price,2)}$ | Vol {round(volume/1e6,1)}M")

    # --- Breakdown SHORT
    for level in levels["breakdown"]:
        if price <= level and ema20 < ema60 and valid_break(level, price) and breakdown_ok(level):
            if volume > vol_thresh and last_signal[symbol] != "SHORT":
                open_trade(symbol, "SHORT", float(last["close"]), atr14)
                last_signal[symbol] = "SHORT"
            elif volume <= vol_thresh:
                send_telegram_message(f"⚠️ Breakdown debole {symbol} | {round(price,2)}$ | Vol {round(volume/1e6,1)}M")

    # Reset segnale se neutro
    if levels["breakdown"][-1] < price < levels["breakout"][0]:
        last_signal[symbol] = None


# --- REPORT TREND ---
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


# --- MAIN LOOP ---
if __name__ == "__main__":
    # Messaggio iniziale SOLO una volta ogni 12 ore
    send_startup_once()

    while True:
        now_it = datetime.now(tz=ZoneInfo("Europe/Rome")).strftime("%H:%M")
        now_utc = datetime.now(tz=ZoneInfo("UTC")).strftime("%H:%M")
        report_msg = f"🕒 Report {now_it} (Italia) | {now_utc} UTC\n"

        trends = {}

        for symbol in ["BTC", "ETH"]:
            analysis = analyze(symbol)
            if analysis:
                price  = analysis["price"]
                volume = analysis["volume"]
                ema20  = analysis["ema20"]
                ema60  = analysis["ema60"]

                # Controlla segnali con nuove regole robuste
                check_signal(symbol, analysis, LEVELS[symbol])

                # Monitora eventuale trade aperto (TP/SL + break-even)
                monitor_trade(symbol, price)

                # Aggiungi trend
                trend_emoji = "🟢" if ema20 > ema60 else "🔴" if ema20 < ema60 else "⚪"
                trends[symbol] = trend_emoji

                report_msg += f"\n{format_report_line(symbol, price, ema20, ema60, volume)}"
            else:
                report_msg += f"\n{symbol}: Errore dati"
                trends[symbol] = "⚪"

        report_msg += f"\n\n{build_suggestion(trends['BTC'], trends['ETH'])}"
        send_telegram_message(report_msg)

        time.sleep(1800)  # Report ogni 30 min
