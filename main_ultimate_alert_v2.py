import os
import csv
import time
import requests
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

# === LIBRERIE PER GRAFICI ===
import io
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

# ---------- FUNZIONI BASE ----------
def calc_ema(data, period):
    """Calcola una EMA semplice su una lista di prezzi."""
    if not data:
        return 0.0
    if len(data) < period:
        return sum(data) / len(data)
    k = 2 / (period + 1)
    ema = data[0]
    for price in data[1:]:
        ema = price * k + ema * (1 - k)
    return ema
# -----------------------------------

# ================== CONFIG ==================
TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"

# Livelli tuo setup
LEVELS = {
    "BTC": {"breakout": [117700, 118300], "breakdown": [116800, 116300]},
    "ETH": {"breakout": [3190, 3250],    "breakdown": [3120, 3070]}
}

# Soglie base
VOLUME_THRESHOLDS = {"BTC": 5_000_000, "ETH": 2_000_000}  # USDT
MIN_MOVE_PCT = 0.2/100

# ATR & gestione trade
ATR_PERIOD   = 14
ATR_SL_MULT  = 1.2
ATR_TP_MULT  = 2.0
MIN_RR       = 1.5

# Buffer/Retest (SICURO)
BUFFER_PCT     = 0.05/100
RETEST_TOL_PCT = 0.02/100

# === Precision Pack toggles ===
USE_MTF            = True    # filtro 1h
USE_MTF_4H         = True    # 4h non deve essere contro trend (opzionale)
USE_VOL_FILTER     = True    # vol 15m > 1.2× mediana 20
VOL_MULT           = 1.2
QUIET_HOURS_UTC    = [(0,3)] # no trade tra 00:00–03:59 UTC
USE_BB_SQUEEZE     = True    # breakout dopo squeeze + close oltre banda
BB_WINDOW          = 20
BB_SQ_THRESHOLD    = 0.06    # (upper-lower)/mid < 6%

# Filtro volatilità avanzato (salta segnali con ATR troppo basso)
USE_ATR_VOL_FILTER = True
ATR_VOL_MIN_PCT    = 0.35/100   # ATR/close ≥ 0.35%

USE_PARTIAL_1R     = True   # chiusura 50% a +1R
USE_TRAILING_CH    = True   # trailing chandelier dopo +1R
CH_PERIOD          = 22
CH_ATR_MULT        = 2.5
USE_TIMESTOP       = True   # esci a BE se dopo X barre MACD contro
TIMESTOP_BARS      = 8

# === Modalità "AGGRESSIVO" ===
USE_AGGR             = True
AGGR_VOL_MULT        = 1.5      # volume ≥ 1.5× mediana 20
AGGR_BUFFER_PCT      = 0.20/100 # chiusura oltre livello di 0.20%
AGGR_MIN_CONFLUENCE  = 2        # min 2 condizioni favorevoli (EMA, MACD, K-D)
AGGR_REQUIRE_RR      = False    # ignora R/R minimo (True per richiederlo)

# ---- Order Flow (volumetrica) ----
USE_BINANCE_CVD   = True      # usa candele Binance con taker-buy per DELTA/CVD/VWAP
USE_CVD_FILTER    = True      # richiedi CVD/DELTA favorevole per segnali "sicuri"
DELTA_SPIKE_MULT  = 1.5       # spike di DELTA per "aggressivo"
USE_VWAP_FILTER   = True      # conferma sopra/sotto VWAP

# Robustezza dati
SEND_SOURCE_IN_REPORT = True        # mostra la fonte dati nel report
HTTP_RETRIES = 3                    # tentativi/endpoint
HTTP_TIMEOUT = 8

# Report giornaliero
DAILY_REPORT_IT_HM = ("23","59")  # Italia

# API
MEXC_KLINE_URL    = "https://api.mexc.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"

# Stato segnali
last_signal      = {"BTC": None, "ETH": None}
last_signal_type = {"BTC": None, "ETH": None}  # "SAFE" o "AGGR"
active_trade     = {"BTC": None, "ETH": None}

# Startup flag 12h
STARTUP_FLAG = "/tmp/bot_startup_flag.txt"
STARTUP_COOLDOWN_SEC = 12 * 3600

TRADES_CSV = "/tmp/trades.csv"
tzIT = ZoneInfo("Europe/Rome")
tzUTC = ZoneInfo("UTC")

# ---------------- TELEGRAM ----------------
def send_telegram_message(message: str):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": message}, timeout=6)
    except Exception as e:
        print("TG error:", e)

def send_photo(buf: bytes, caption: str):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                      data={"chat_id": CHAT_ID, "caption": caption},
                      files={"photo": ("chart.png", buf)}, timeout=18)
    except Exception as e:
        print("TG photo error:", e)

def send_startup_once():
    try:
        if os.path.exists(STARTUP_FLAG):
            with open(STARTUP_FLAG,"r") as f:
                ts = float((f.read() or "0").strip())
            if time.time() - ts < STARTUP_COOLDOWN_SEC:
                return
        send_telegram_message("✅ Bot PRO attivo – Precision Pack v1 + Aggressive Mode + Volatility + CVD/VWAP")
        with open(STARTUP_FLAG,"w") as f:
            f.write(str(time.time()))
    except Exception as e:
        print("startup flag err:", e)

# ---------------- DATA (ROBUST) ----------------
def http_get(url):
    last_err = None
    for i in range(HTTP_RETRIES):
        try:
            r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(0.3 * (2**i))  # backoff 0.3s, 0.6s, 1.2s
    print("[http_get] fail:", url, "|", last_err)
    return None

def _df_common_indicators(df):
    # ATR
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"]-df["low"]).abs(),
        (df["high"]-prev_close).abs(),
        (df["low"] -prev_close).abs()
    ], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean().bfill()

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]

    # KDJ
    low_min  = df["low"].rolling(window=9, min_periods=9).min()
    high_max = df["high"].rolling(window=9, min_periods=9).max()
    denom = (high_max - low_min).replace(0, np.nan)
    rsv = (df["close"] - low_min) / denom * 100
    df["K"] = rsv.ewm(com=2, adjust=False).mean()
    df["D"] = df["K"].ewm(com=2, adjust=False).mean()
    df["J"] = 3*df["K"] - 2*df["D"]

    # Bollinger
    mid = df["close"].rolling(BB_WINDOW).mean()
    std = df["close"].rolling(BB_WINDOW).std()
    df["BB_MID"] = mid
    df["BB_UP"]  = mid + 2*std
    df["BB_LOW"] = mid - 2*std
    df["BB_BW"]  = (df["BB_UP"]-df["BB_LOW"])/mid

    # MTF EMAs
    df["EMA50"]  = df["close"].ewm(span=50, adjust=False).mean()
    df["EMA200"] = df["close"].ewm(span=200, adjust=False).mean()
    return df

def build_df_binance(symbol, interval="15m", limit=120):
    """Preferita: ha taker-buy per DELTA/CVD e VWAP."""
    data = http_get(BINANCE_KLINE_URL.format(symbol=symbol, interval=interval, limit=limit))
    if not isinstance(data, list) or not data:
        return None, None
    rows = []
    for k in data:
        rows.append({
            "open_time":  pd.to_datetime(int(k[0]), unit="ms"),
            "open":  float(k[1]), "high": float(k[2]), "low": float(k[3]),
            "close": float(k[4]), "volume": float(k[5]),
            "close_time": pd.to_datetime(int(k[6]), unit="ms"),
            "tbb": float(k[9]) if len(k) > 9 else None
        })
    df = pd.DataFrame(rows).sort_values("close_time").reset_index(drop=True)

    # Order-flow
    if df["tbb"].notna().any():
        df["tbs"]   = (df["volume"] - df["tbb"]).clip(lower=0)
        df["DELTA"] = df["tbb"] - df["tbs"]
        df["CVD"]   = df["DELTA"].cumsum()
        df["CVD_SLOPE"] = df["CVD"].diff()

        # VWAP intraday
        day = df["close_time"].dt.date
        typical = (df["high"]+df["low"]+df["close"])/3
        df["cum_pv"] = (typical*df["volume"]).groupby(day).cumsum()
        df["cum_v"]  = df["volume"].groupby(day).cumsum()
        df["VWAP"]   = df["cum_pv"] / df["cum_v"]

    df = _df_common_indicators(df)
    return df, "Binance"

def build_df_mexc(symbol, interval="15m", limit=120):
    """Fallback: nessun DELTA/CVD/VWAP, ma mantiene gli indicatori classici."""
    data = http_get(MEXC_KLINE_URL.format(symbol=symbol, interval=interval, limit=limit))
    if not isinstance(data, list) or not data:
        return None, None
    rows = []
    for r in data:
        open_time, open_, high, low, close, volume, close_time = r[:7]
        rows.append({
            "open_time":  pd.to_datetime(int(open_time), unit="ms"),
            "open":  float(open_), "high": float(high), "low": float(low),
            "close": float(close), "volume": float(volume),
            "close_time": pd.to_datetime(int(close_time), unit="ms"),
        })
    df = pd.DataFrame(rows).sort_values("close_time").reset_index(drop=True)
    df = _df_common_indicators(df)
    return df, "MEXC"

def build_df_unified(symbol, interval="15m", limit=120):
    """
    Prova prima Binance (con order-flow).
    Se fallisce, passa a MEXC in automatico.
    Ritorna (df, source) oppure (None, None).
    """
    df, src = build_df_binance(symbol, interval, limit)
    if isinstance(df, pd.DataFrame) and len(df) > 50:
        return df, src
    df, src = build_df_mexc(symbol, interval, limit)
    if isinstance(df, pd.DataFrame) and len(df) > 50:
        return df, src
    return None, None

# ------------- NOTIFICA + GRAFICO -------------
def build_chart_for(symbol, entry, tp, sl, kind="SAFE"):
    df, _ = build_df_unified(symbol, "15m", 120)
    if df is None: raise RuntimeError("No data")

    fig, (ax1, ax2, ax3) = plt.subplots(3,1,figsize=(11,8),sharex=True,
                                        gridspec_kw={'height_ratios':[3,1,1]})
    ax1.plot(df["close_time"], df["close"], label=f"{symbol}/USDT")
    if "VWAP" in df.columns:
        ax1.plot(df["close_time"], df["VWAP"], linewidth=1.6, label="VWAP")
    ax1.grid(True, linewidth=0.4)

    # palette per tipo segnale
    if kind == "SAFE":
        c_entry, c_tp, c_sl = "#16a34a", "#f59e0b", "#ef4444"      # verde / arancio / rosso
    else:
        c_entry, c_tp, c_sl = "#06b6d4", "#8b5cf6", "#64748b"      # ciano / viola / grigio

    ax1.axhline(entry, color=c_entry, linestyle="--",      linewidth=2.2, label="Entrata")
    ax1.axhline(tp,    color=c_tp,    linestyle=(0,(9,4)), linewidth=2.2, label="Target")
    ax1.axhline(sl,    color=c_sl,    linestyle=(0,(3,3)), linewidth=2.2, label="Stop")

    def annotate(y, text, c):
        ax1.text(df["close_time"].iloc[-1], y, f"  {text}", color=c,
                 va="center", fontsize=10, bbox=dict(facecolor="white", alpha=0.7, edgecolor=c))
    annotate(entry, f"Entrata {round(entry,2)}", c_entry)
    annotate(tp,    f"Target {round(tp,2)}",     c_tp)
    annotate(sl,    f"Stop {round(sl,2)}",       c_sl)

    ax1.set_ylabel("USDT"); ax1.legend(loc="upper left")

    colors = np.where(df["MACD_HIST"]>=0, "#16a34a", "#ef4444")
    ax2.bar(df["close_time"], df["MACD_HIST"], color=colors, label="Hist")
    ax2.plot(df["close_time"], df["MACD"], label="MACD")
    ax2.plot(df["close_time"], df["MACD_SIGNAL"], label="Signal")
    ax2.grid(True, linewidth=0.4); ax2.legend(loc="upper left")

    ax3.plot(df["close_time"], df["K"], label="K")
    ax3.plot(df["close_time"], df["D"], label="D")
    ax3.plot(df["close_time"], df["J"], label="J")
    ax3.grid(True, linewidth=0.4); ax3.legend(loc="upper left")

    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    plt.xticks(rotation=45); plt.tight_layout()
    buf = io.BytesIO(); plt.savefig(buf, format="png", dpi=220, bbox_inches="tight")
    plt.close(fig); buf.seek(0)
    return buf.getvalue()

def notify_signal(symbol, direction, entry, tp, sl, kind="SAFE", rr=None, extra_text=""):
    if kind == "SAFE":
        title = f"✅ ENTRATA SICURA {direction} {symbol} 15m | Ingresso {round(entry,2)}"
        note  = "✔️ Tutte le conferme attive"
    else:
        title = f"🚀 BREAKOUT AGGRESSIVO {direction} {symbol} 15m | Ingresso {round(entry,2)}"
        note  = "⚠️ Segnale ad alto rischio (conferme parziali)"
    send_telegram_message(title)
    rr_txt = f" | R/R ≈ {rr:.2f}" if rr is not None else ""
    if extra_text:
        extra_text = "\n" + extra_text
    send_telegram_message(f"🎯 Target: {round(tp,2)}   🛑 Stop: {round(sl,2)}{rr_txt}\n⏱️ TF: 15m   {note}{extra_text}")
    try:
        send_photo(build_chart_for(symbol, entry, tp, sl, kind), f"📸 Grafico 15m ({'Sicuro' if kind=='SAFE' else 'Aggressivo'})")
    except Exception as e:
        print("chart err:", e)

# ------------- UTILITY -------------
def in_quiet_hours_now():
    now_utc = datetime.now(tzUTC).hour
    for start,end in QUIET_HOURS_UTC:
        if start <= now_utc <= end:
            return True
    return False

def mtf_filter(symbol, direction):
    """Richiede 1h allineato e (se attivo) 4h non opposto netto."""
    if not USE_MTF: 
        return True

    df1h, _ = build_df_unified(symbol, "1h", 300)
    if df1h is None or len(df1h) < 200:
        ok1h = True
    else:
        ema50_1h, ema200_1h = df1h["EMA50"].iloc[-1], df1h["EMA200"].iloc[-1]
        ok1h = (direction=="LONG" and ema50_1h>ema200_1h) or (direction=="SHORT" and ema50_1h<ema200_1h)

    if not USE_MTF_4H:
        return ok1h

    df4h, _ = build_df_unified(symbol, "4h", 300)
    if df4h is None or len(df4h) < 200:
        ok4h = True
    else:
        ema50_4h, ema200_4h = df4h["EMA50"].iloc[-1], df4h["EMA200"].iloc[-1]
        ok4h = not ((direction=="LONG" and ema50_4h<ema200_4h) or (direction=="SHORT" and ema50_4h>ema200_4h))
    return ok1h and ok4h

def vol_filter(df15):
    if not USE_VOL_FILTER: return True
    v = df15["volume"].iloc[-1]
    med = df15["volume"].tail(20).median()
    return v > VOL_MULT*med

def aggr_vol_ok(df15):
    v = df15["volume"].iloc[-1]
    med = df15["volume"].tail(20).median()
    return v >= AGGR_VOL_MULT*med

def atr_vol_ok(df15):
    """ATR/close deve essere >= soglia per evitare mercato troppo piatto."""
    if not USE_ATR_VOL_FILTER: 
        return True
    atr = df15["ATR"].iloc[-1]
    close = df15["close"].iloc[-1]
    return (atr / max(close,1e-9)) >= ATR_VOL_MIN_PCT

# ---- Filtri volumetrici (Order Flow) ----
def cvd_filter_ok(df15, direction):
    if not USE_CVD_FILTER: 
        return True
    if "DELTA" not in df15.columns or "CVD_SLOPE" not in df15.columns:
        return True
    last = df15.iloc[-1]
    if direction == "LONG":
        return (last.get("DELTA",0) > 0) and (last.get("CVD_SLOPE",0) > 0)
    else:
        return (last.get("DELTA",0) < 0) and (last.get("CVD_SLOPE",0) < 0)

def delta_spike(df15):
    if "DELTA" not in df15.columns:
        return False
    med = df15["DELTA"].abs().tail(20).median()
    return abs(df15["DELTA"].iloc[-1]) >= DELTA_SPIKE_MULT * max(med, 1e-9)

def vwap_filter_ok(df15, direction):
    if not USE_VWAP_FILTER or "VWAP" not in df15.columns:
        return True
    last = df15.iloc[-1]
    return (direction=="LONG" and last["close"] >= last["VWAP"]) or \
           (direction=="SHORT" and last["close"] <= last["VWAP"])

def rr_ok(entry, tp, sl):
    risk = abs(entry - sl); reward = abs(tp - entry)
    rr = reward/max(risk,1e-9)
    return rr >= MIN_RR, rr

def confluence_score(df15, direction):
    last = df15.iloc[-1]
    ema_ok  = (last["EMA50"] > last["EMA200"]) if direction=="LONG" else (last["EMA50"] < last["EMA200"])
    macd_ok = (last["MACD"] > last["MACD_SIGNAL"]) if direction=="LONG" else (last["MACD"] < last["MACD_SIGNAL"])
    kd_ok   = (last["K"] > last["D"]) if direction=="LONG" else (last["K"] < last["D"])
    return sum([ema_ok, macd_ok, kd_ok])

def log_trade(row):
    header = ["time_utc","symbol","direction","kind","entry","tp","sl","exit_price","result","rr"]
    exists = os.path.exists(TRADES_CSV)
    with open(TRADES_CSV,"a",newline="") as f:
        w=csv.writer(f)
        if not exists: w.writerow(header)
        w.writerow(row)

# ------------- ANALISI/SEGNALI -------------
def analyze(symbol):
    df, source = build_df_unified(symbol, "15m", 120)
    if df is None:
        send_telegram_message(f"⚠️ Errore dati {symbol} (tutte le fonti)")
        return None
    closes = df["close"].tolist()
    vols   = df["volume"].tolist()
    last_close = closes[-1]
    last_vol   = closes[-1]*vols[-1]
    ema20 = calc_ema(closes[-20:], 20)
    ema60 = calc_ema(closes[-60:], 60)
    atr14 = df["ATR"].iloc[-1]
    return {"price": last_close, "volume": last_vol, "ema20": ema20, "ema60": ema60,
            "atr": atr14, "df": df, "source": source}

def open_trade(symbol, direction, entry_price, atr, kind="SAFE", rr_checked=True, extra_text=""):
    if direction=="LONG":
        sl = entry_price - ATR_SL_MULT*atr
        tp = entry_price + ATR_TP_MULT*atr
    else:
        sl = entry_price + ATR_SL_MULT*atr
        tp = entry_price - ATR_TP_MULT*atr

    rr_ok_flag, rr_val = True, None
    if not rr_checked:
        rr_ok_flag, rr_val = rr_ok(entry_price, tp, sl)
        if not rr_ok_flag:
            send_telegram_message(f"⏭️ {symbol} {direction}: R/R {rr_val:.2f} < {MIN_RR}, skip")
            return

    active_trade[symbol] = {
        "direction": direction, "entry": entry_price, "tp": tp, "sl": sl,
        "opened_at": datetime.now(tzUTC), "moved_to_be": False,
        "touched_1R": False, "partial_done": False, "kind": kind
    }
    notify_signal(symbol, direction, entry_price, tp, sl, kind, rr_val, extra_text)

def monitor_trade(symbol, price, df15):
    t = active_trade[symbol]
    if not t: return
    direction = t["direction"]; entry = t["entry"]; tp=t["tp"]; sl=t["sl"]; kind=t["kind"]

    risk = abs(entry-sl)
    if not t["touched_1R"]:
        if (direction=="LONG" and price >= entry + risk) or (direction=="SHORT" and price <= entry - risk):
            t["touched_1R"] = True
            send_telegram_message(f"🥇 {symbol} {direction} ({kind}): +1R raggiunto")
            if USE_PARTIAL_1R and not t["partial_done"]:
                t["partial_done"] = True
                send_telegram_message(f"💰 {symbol}: chiusa PARZIALE 50% a +1R (simulato)")

    if USE_TRAILING_CH and t["touched_1R"]:
        if len(df15) >= CH_PERIOD:
            if direction=="LONG":
                hh = df15["high"].tail(CH_PERIOD).max()
                ch = hh - CH_ATR_MULT*df15["ATR"].iloc[-1]
                t["sl"] = max(t["sl"], ch)
            else:
                ll = df15["low"].tail(CH_PERIOD).min()
                ch = ll + CH_ATR_MULT*df15["ATR"].iloc[-1]
                t["sl"] = min(t["sl"], ch)

    if USE_TIMESTOP:
        bars = int((datetime.now(tzUTC) - t["opened_at"]).total_seconds() // (15*60))
        macd = df15["MACD"].iloc[-1]; sig = df15["MACD_SIGNAL"].iloc[-1]
        macd_against = (direction=="LONG" and macd<sig) or (direction=="SHORT" and macd>sig)
        if bars >= TIMESTOP_BARS and macd_against:
            t["sl"] = entry
            send_telegram_message(f"⏱️ {symbol} {direction} ({kind}): time-stop → SL a BE")

    if direction=="LONG":
        if price >= tp:
            send_telegram_message(f"✅ TP LONG {symbol} ({kind}) a {round(tp,2)}")
            log_trade([datetime.now(tzUTC),symbol,"LONG",kind,entry,tp,t['sl'],tp,"TP",round((tp-entry)/risk,2)])
            active_trade[symbol]=None; return
        if price <= t["sl"]:
            res = "BE" if abs(t["sl"]-entry)<1e-8 else "SL"
            send_telegram_message(f"❌ {res} LONG {symbol} ({kind}) a {round(t['sl'],2)}")
            log_trade([datetime.now(tzUTC),symbol,"LONG",kind,entry,tp,t['sl'],t['sl'],res,round((tp-entry)/risk,2)])
            active_trade[symbol]=None; return
    else:
        if price <= tp:
            send_telegram_message(f"✅ TP SHORT {symbol} ({kind}) a {round(tp,2)}")
            log_trade([datetime.now(tzUTC),symbol,"SHORT",kind,entry,tp,t['sl'],tp,"TP",round((entry-tp)/risk,2)])
            active_trade[symbol]=None; return
        if price >= t["sl"]:
            res = "BE" if abs(t["sl"]-entry)<1e-8 else "SL"
            send_telegram_message(f"❌ {res} SHORT {symbol} ({kind}) a {round(t['sl'],2)}")
            log_trade([datetime.now(tzUTC),symbol,"SHORT",kind,entry,tp,t['sl'],t['sl'],res,round((entry-tp)/risk,2)])
            active_trade[symbol]=None; return

# ------------- CHECK SEGNALE -------------
def squeeze_ok(df15, direction):
    if not USE_BB_SQUEEZE: return True
    last = df15.iloc[-1]
    recent = df15.tail(10)
    sq = (recent["BB_BW"] < BB_SQ_THRESHOLD).any()
    if not sq: return False
    if direction=="LONG":
        return last["close"] > last["BB_UP"]
    else:
        return last["close"] < last["BB_LOW"]

def check_signal(symbol, an, levels):
    global last_signal, last_signal_type
    df = an["df"]; price = an["price"]; ema20=an["ema20"]; ema60=an["ema60"]; atr=an["atr"]
    volume_usdt = an["volume"]; vol_thresh = VOLUME_THRESHOLDS[symbol]

    if in_quiet_hours_now() and USE_VOL_FILTER:
        return

    last = df.iloc[-1]; prev=df.iloc[-2]

    def valid_break(level, current_price):  # legacy
        return abs((current_price-level)/level) > MIN_MOVE_PCT

    def breakout_ok(level):
        buf = level*(1+BUFFER_PCT); ret = level*(1+RETEST_TOL_PCT)
        cond_a = last["close"]>buf and prev["close"]<=buf
        cond_b = (last["low"]<=ret) and (last["close"]>buf)
        return cond_a or cond_b

    def breakdown_ok(level):
        buf = level*(1-BUFFER_PCT); ret = level*(1-RETEST_TOL_PCT)
        cond_a = last["close"]<buf and prev["close"]>=buf
        cond_b = (last["high"]>=ret) and (last["close"]<buf)
        return cond_a or cond_b

    # ====== SICURO ======
    # Long
    for level in levels["breakout"]:
        if price>=level and ema20>ema60 and valid_break(level,price) and breakout_ok(level):
            if volume_usdt>vol_thresh and (last_signal[symbol]!="LONG"):
                if USE_ATR_VOL_FILTER and not atr_vol_ok(df): 
                    send_telegram_message(f"⏭️ {symbol} LONG: volatilità troppo bassa"); continue
                if USE_VOL_FILTER and not vol_filter(df): 
                    send_telegram_message(f"⏭️ {symbol} LONG: vol debole"); continue
                if USE_BB_SQUEEZE and not squeeze_ok(df,"LONG"):
                    send_telegram_message(f"⏭️ {symbol} LONG: no squeeze/banda"); continue
                if not mtf_filter(symbol,"LONG"):
                    send_telegram_message(f"⏭️ {symbol} LONG: MTF non allineato"); continue
                if not cvd_filter_ok(df, "LONG"):
                    send_telegram_message(f"⏭️ {symbol} LONG: CVD/DELTA non favorevole"); continue
                if not vwap_filter_ok(df, "LONG"):
                    send_telegram_message(f"⏭️ {symbol} LONG: Sopra VWAP richiesto"); continue

                extra = ""
                if "DELTA" in df.columns:
                    extra = f"Δ: {round(df['DELTA'].iloc[-1],2)} | CVD slope: {round(df['CVD_SLOPE'].iloc[-1],2)}"
                open_trade(symbol,"LONG", float(last["close"]), atr, kind="SAFE", rr_checked=False, extra_text=extra)
                last_signal[symbol]="LONG"; last_signal_type[symbol]="SAFE"
            elif volume_usdt<=vol_thresh:
                send_telegram_message(f"⚠️ Breakout debole {symbol} | {round(price,2)}$ | Vol {round(volume_usdt/1e6,1)}M")

    # Short
    for level in levels["breakdown"]:
        if price<=level and ema20<ema60 and valid_break(level,price) and breakdown_ok(level):
            if volume_usdt>vol_thresh and (last_signal[symbol]!="SHORT"):
                if USE_ATR_VOL_FILTER and not atr_vol_ok(df): 
                    send_telegram_message(f"⏭️ {symbol} SHORT: volatilità troppo bassa"); continue
                if USE_VOL_FILTER and not vol_filter(df):
                    send_telegram_message(f"⏭️ {symbol} SHORT: vol debole"); continue
                if USE_BB_SQUEEZE and not squeeze_ok(df,"SHORT"):
                    send_telegram_message(f"⏭️ {symbol} SHORT: no squeeze/banda"); continue
                if not mtf_filter(symbol,"SHORT"):
                    send_telegram_message(f"⏭️ {symbol} SHORT: MTF non allineato"); continue
                if not cvd_filter_ok(df, "SHORT"):
                    send_telegram_message(f"⏭️ {symbol} SHORT: CVD/DELTA non favorevole"); continue
                if not vwap_filter_ok(df, "SHORT"):
                    send_telegram_message(f"⏭️ {symbol} SHORT: Sotto VWAP richiesto"); continue

                extra = ""
                if "DELTA" in df.columns:
                    extra = f"Δ: {round(df['DELTA'].iloc[-1],2)} | CVD slope: {round(df['CVD_SLOPE'].iloc[-1],2)}"
                open_trade(symbol,"SHORT", float(last["close"]), atr, kind="SAFE", rr_checked=False, extra_text=extra)
                last_signal[symbol]="SHORT"; last_signal_type[symbol]="SAFE"
            elif volume_usdt<=vol_thresh:
                send_telegram_message(f"⚠️ Breakdown debole {symbol} | {round(price,2)}$ | Vol {round(volume_usdt/1e6,1)}M")

    # ====== AGGRESSIVO ======
    if USE_AGGR and active_trade[symbol] is None:
        # LONG aggressivo
        for level in levels["breakout"]:
            buf_aggr = level*(1+AGGR_BUFFER_PCT)
            if (last["close"]>buf_aggr and ema20>=ema60 and valid_break(level, price)):
                if aggr_vol_ok(df) and confluence_score(df,"LONG") >= AGGR_MIN_CONFLUENCE and (not USE_CVD_FILTER or delta_spike(df)):
                    rr_needed = AGGR_REQUIRE_RR
                    extra = ""
                    if "DELTA" in df.columns:
                        extra = f"Δ spike: {round(df['DELTA'].iloc[-1],2)}"
                    open_trade(symbol,"LONG", float(last["close"]), atr, kind="AGGR", rr_checked=rr_needed, extra_text=extra)
                    last_signal[symbol]="LONG"; last_signal_type[symbol]="AGGR"
                    break

        # SHORT aggressivo
        for level in levels["breakdown"]:
            buf_aggr = level*(1-AGGR_BUFFER_PCT)
            if (last["close"]<buf_aggr and ema20<=ema60 and valid_break(level, price)):
                if aggr_vol_ok(df) and confluence_score(df,"SHORT") >= AGGR_MIN_CONFLUENCE and (not USE_CVD_FILTER or delta_spike(df)):
                    rr_needed = AGGR_REQUIRE_RR
                    extra = ""
                    if "DELTA" in df.columns:
                        extra = f"Δ spike: {round(df['DELTA'].iloc[-1],2)}"
                    open_trade(symbol,"SHORT", float(last["close"]), atr, kind="AGGR", rr_checked=rr_needed, extra_text=extra)
                    last_signal[symbol]="SHORT"; last_signal_type[symbol]="AGGR"
                    break

    # Reset segnale se neutro
    if levels["breakdown"][-1] < price < levels["breakout"][0]:
        last_signal[symbol]=None
        last_signal_type[symbol]=None

# ------------- REPORT -------------
def format_report_line(symbol, df, price, ema20, ema60, volume, source=None):
    trend = "🟢" if ema20>ema60 else "🔴" if ema20<ema60 else "⚪"
    base = f"{trend} {symbol}: {round(price,2)}$ | EMA20:{round(ema20,2)} | EMA60:{round(ema60,2)} | Vol:{round(volume/1e6,1)}M"
    if "VWAP" in df.columns:
        base += " | " + ("↑ sopra VWAP" if price>=df['VWAP'].iloc[-1] else "↓ sotto VWAP")
    if "DELTA" in df.columns and "CVD_SLOPE" in df.columns:
        base += f" | Δ:{round(df['DELTA'].iloc[-1],2)} | CVDΔ:{round(df['CVD_SLOPE'].iloc[-1],2)}"
    if SEND_SOURCE_IN_REPORT and source:
        base += f" | src:{source}"
    return base

def build_suggestion(btc_trend, eth_trend):
    if btc_trend=="🟢" and eth_trend=="🟢": return "Suggerimento: Preferenza LONG ✅"
    if btc_trend=="🔴" and eth_trend=="🔴": return "Suggerimento: Preferenza SHORT ❌"
    return "Suggerimento: Trend misto – Attendere conferma ⚠️"

def maybe_send_daily_report():
    now_it = datetime.now(tzIT)
    hh, mm = DAILY_REPORT_IT_HM
    if now_it.strftime("%H")==hh and now_it.strftime("%M")==mm:
        if os.path.exists(TRADES_CSV):
            try:
                df = pd.read_csv(TRADES_CSV)
                today = date.today().isoformat()
                df["time_utc"] = pd.to_datetime(df["time_utc"])
                today_df = df[df["time_utc"].dt.date.astype(str)==today]
                if len(today_df):
                    wr = (today_df["result"]=="TP").mean()
                    msg = f"📊 Daily report {today}: trades {len(today_df)}, win-rate {wr*100:.0f}%, R medio ≈ {today_df['rr'].mean():.2f}"
                else:
                    msg = f"📊 Daily report {today}: nessun trade."
                send_telegram_message(msg)
            except Exception as e:
                print("daily report err:", e)

# ------------- MAIN LOOP -------------
if __name__ == "__main__":
    send_startup_once()
    while True:
        now_it  = datetime.now(tzIT).strftime("%H:%M")
        now_utc = datetime.now(tzUTC).strftime("%H:%M")
        report_msg = f"🕒 Report {now_it} (Italia) | {now_utc} UTC\n"
        trends = {}

        for symbol in ["BTC","ETH"]:
            an = analyze(symbol)
            if an:
                price, vol, ema20, ema60, df, src = an["price"], an["volume"], an["ema20"], an["ema60"], an["df"], an.get("source")
                check_signal(symbol, an, LEVELS[symbol])
                monitor_trade(symbol, price, df)
                trends[symbol] = "🟢" if ema20>ema60 else "🔴" if ema20<ema60 else "⚪"
                report_msg += f"\n{format_report_line(symbol, df, price, ema20, ema60, vol, src)}"
            else:
                report_msg += f"\n{symbol}: Errore dati"; trends[symbol]="⚪"

        report_msg += f"\n\n{build_suggestion(trends['BTC'], trends['ETH'])}"
        send_telegram_message(report_msg)

        maybe_send_daily_report()
        time.sleep(1800)  # ogni 30 minuti
