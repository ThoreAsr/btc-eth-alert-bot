import requests
import pandas as pd
import numpy as np
import time
import io
from datetime import datetime, timedelta

# ZoneInfo con fallback per ambienti <3.9
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    from backports.zoneinfo import ZoneInfo  # fallback per <3.9

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ==========================
# CONFIG
# ==========================
CAPITALE = 2000

# Rischio & qualità
RISK_PERCENT_ACCEPTANCE = 0.01   # 1% per segnali "sicuri"
RISK_PERCENT_SPIKE      = 0.005  # 0.5% per spike
RR_MIN_ACCEPTANCE       = 1.5
RR_MIN_SPIKE            = 1.2

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
TIMEFRAMES = ["15m", "30m"]

# Filtri volume dinamici per TF (Acceptance)
TF_SETTINGS = {
    "15m": {"vol_window": 10, "vol_mult": 1.10},
    "30m": {"vol_window": 20, "vol_mult": 1.20},
}

# Volume Profile
BINS_PROFILE = 60

# Gestione segnale
COOLDOWN_MIN = 15
HEARTBEAT_MIN = 30
NEWS_SPIKE_MULT = 2.5

# Failsafe / promemoria
NO_SIGNAL_ALERT_HOURS    = 36
NO_SIGNAL_REMINDER_HOURS = 6

# Modalità ⚡Spike
SPIKE_RANGE_PCT = 0.02    # 2% min
SPIKE_VOL_MULT  = 2.0     # vol >= 2x media

# CoinMarketCap (volumi globali)
CMC_API_KEY = "e1bf46bf-1e42-4c30-8847-c011f772dcc8"
CMC_REFRESH_SEC = 600

# Telegram
BOT_TOKEN = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "356760541"

# Timezone IT
TZ = ZoneInfo("Europe/Rome")

# ==========================
# UTILS
# ==========================
def fmt(x, nd=2):
    try:
        return f"{x:,.{nd}f}"
    except Exception:
        return str(x)

def now_local():
    return datetime.now(TZ)

def ts_label():
    return f"{now_local().strftime('%Y-%m-%d %H:%M:%S')} CET/CEST"

def send_telegram_text(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print("Errore invio Telegram (text):", e)

def send_telegram_photo(caption: str, image_bytes: bytes):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes, "image/png")}
    data = {"chat_id": CHAT_ID, "caption": caption}
    try:
        requests.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        print("Errore invio Telegram (photo):", e)

# ==========================
# DATA (MEXC)
# ==========================
def get_ohlcv(symbol="BTCUSDT", interval="15m", limit=300):
    """
    OHLCV da MEXC (compatibile con Binance kline).
    https://api.mexc.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=300
    """
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "time","open","high","low","close","volume","c1","c2","c3","c4","c5","c6"
    ])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(TZ)
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    return df[["time","open","high","low","close","volume"]]

_cmc_cache = {}  # { "BTC": (volume, ts_epoch) }
def get_global_volume(symbol_root="BTC"):
    now_epoch = time.time()
    vol, ts = _cmc_cache.get(symbol_root, (None, 0))
    if vol is not None and (now_epoch - ts) < CMC_REFRESH_SEC:
        return vol
    try:
        url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol_root}"
        headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        j = r.json()
        vol = j["data"][symbol_root]["quote"]["USD"]["volume_24h"]
        _cmc_cache[symbol_root] = (vol, now_epoch)
        return vol
    except Exception as e:
        print("Errore CMC:", e)
        return vol if vol is not None else 0.0

# ==========================
# VOLUME PROFILE
# ==========================
def build_volume_profile(df: pd.DataFrame, bins=BINS_PROFILE):
    prices = (df["high"] + df["low"]) / 2.0
    volumes = df["volume"]
    hist, edges = np.histogram(prices, bins=bins, weights=volumes)
    if hist.sum() == 0:
        return None, None, None
    max_idx = int(np.argmax(hist))
    poc = (edges[max_idx] + edges[max_idx + 1]) / 2.0
    total = hist.sum()
    order = np.argsort(hist)[::-1]
    cum, area_bins = 0.0, []
    for idx in order:
        cum += hist[idx]
        area_bins.append((edges[idx], edges[idx + 1]))
        if cum >= 0.70 * total:
            break
    vah = max(b[1] for b in area_bins)
    val = min(b[0] for b in area_bins)
    return float(poc), float(vah), float(val)

# ==========================
# PLOT
# ==========================
def make_chart_png(df: pd.DataFrame, symbol: str, tf: str, poc: float, vah: float, val: float) -> bytes:
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(df["time"], df["close"], linewidth=1.5, label="Close")
    ax.axhline(poc, linestyle="--", linewidth=1, label=f"POC {fmt(poc)}")
    ax.axhline(vah, linestyle="-.", linewidth=1, label=f"VAH {fmt(vah)}")
    ax.axhline(val, linestyle="-.", linewidth=1, label=f"VAL {fmt(val)}")
    ax.set_title(f"{symbol} • TF {tf} • {ts_label()}")
    ax.set_xlabel("Tempo (IT)")
    ax.set_ylabel("Prezzo")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, linewidth=0.3, alpha=0.4)
    buf = io.BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.read()

# ==========================
# SIGNAL ENGINE
# ==========================
def acceptance_check(df: pd.DataFrame, vah: float, val: float, vol_window: int, vol_mult: float):
    close = df["close"].values
    vol = df["volume"].values
    if len(close) < max(22, vol_window + 2):
        return None
    avg_vol = vol[-(vol_window+1):-1].mean()
    last_vol = vol[-1]
    last2_above_vah = close[-1] > vah and close[-2] > vah
    last2_below_val = close[-1] < val and close[-2] < val
    long_ok = last2_above_vah and (last_vol > vol_mult * avg_vol)
    short_ok = last2_below_val and (last_vol > vol_mult * avg_vol)
    return {"long": bool(long_ok), "short": bool(short_ok), "avg_vol": float(avg_vol), "last_vol": float(last_vol)}

def spike_check(df: pd.DataFrame, vah: float, val: float, vol_window: int):
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    vol   = df["volume"].values
    if len(close) < vol_window + 2:
        return None
    prev_close = close[-2]
    last_close = close[-1]
    last_high  = high[-1]
    last_low   = low[-1]
    rng_pct = abs(last_high - last_low) / prev_close
    avg_vol = vol[-(vol_window+1):-1].mean()
    last_vol = vol[-1]
    if rng_pct >= SPIKE_RANGE_PCT and last_vol >= SPIKE_VOL_MULT * avg_vol:
        if last_close > vah:
            return {"side": "BUY", "rng_pct": float(rng_pct), "avg_vol": float(avg_vol), "last_vol": float(last_vol)}
        if last_close < val:
            return {"side": "SELL", "rng_pct": float(rng_pct), "avg_vol": float(avg_vol), "last_vol": float(last_vol)}
        if last_close > prev_close:
            return {"side": "BUY", "rng_pct": float(rng_pct), "avg_vol": float(avg_vol), "last_vol": float(last_vol)}
        else:
            return {"side": "SELL", "rng_pct": float(rng_pct), "avg_vol": float(avg_vol), "last_vol": float(last_vol)}
    return None

def volatility_spike_flag(df: pd.DataFrame, mult=NEWS_SPIKE_MULT):
    rng = (df["high"] - df["low"]).values
    if len(rng) < 22:
        return False
    avg_rng = rng[-21:-1].mean()
    last_rng = rng[-1]
    return last_rng > mult * avg_rng

def rr_compute(entry: float, stop: float, tp: float, risk_usd: float):
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return None, None, None
    size = risk_usd / stop_dist
    profit = size * abs(tp - entry)
    rr = profit / risk_usd if risk_usd > 0 else 0
    return size, profit, rr

_last_signal = {}  # (symbol, side, kind) -> (ts, entry)
def should_send_signal(symbol: str, side: str, kind: str, entry: float, cooldown_min=COOLDOWN_MIN, tol=0.002):
    key = (symbol, side, kind)
    last = _last_signal.get(key)
    now = now_local()
    if last:
        ts, last_entry = last
        if (now - ts) < timedelta(minutes=cooldown_min) and abs(entry - last_entry) / entry < tol:
            return False
    _last_signal[key] = (now, entry)
    return True

# Stato heartbeat e segnali
_last_heartbeat         = now_local() - timedelta(minutes=HEARTBEAT_MIN+1)
_last_any_signal        = now_local() - timedelta(hours=NO_SIGNAL_ALERT_HOURS+1)
_last_no_signal_notice  = now_local() - timedelta(hours=NO_SIGNAL_REMINDER_HOURS+1)

def build_levels_report(levels_map, news_flags, cmc_map):
    lines = ["=============================", "🫀 HEARTBEAT – Livelli chiave", f"⏰ {ts_label()}"]
    for sym in SYMBOLS:
        root = sym.replace("USDT", "")
        lines.append(f"\n{sym} | Vol 24h (CMC): {fmt(cmc_map.get(root,0),0)}")
        for tf in TIMEFRAMES:
            k = (sym, tf)
            d = levels_map.get(k)
            if not d:
                continue
            bias = "BULL" if d["close"] > d["vah"] else ("BEAR" if d["close"] < d["val"] else "NEUTRAL")
            news = " ⚠️ NEWS MODE" if news_flags.get(k, False) else ""
            lines.append(f"[{tf}] Close {fmt(d['close'])} | POC {fmt(d['poc'])} | VAH {fmt(d['vah'])} | VAL {fmt(d['val'])} | Bias {bias}{news}")
    lines.append("=============================")
    return "\n".join(lines)

def signal_caption(symbol, tfs_ok, side, kind, entry, stop, tp1, tp2, poc, vah, val, vol_bar, vol_avg, vol_glob, size, profit, rr, extra_note=""):
    tag = "✅ ACCEPTANCE" if kind == "ACCEPTANCE" else "⚡ SPIKE"
    note = f"\n{extra_note}" if extra_note else ""
    risk_pct = RISK_PERCENT_ACCEPTANCE if kind == "ACCEPTANCE" else RISK_PERCENT_SPIKE
    return f"""
{tag} – {symbol}
⏰ {ts_label()}
TF confermati: {", ".join(tfs_ok)}
Side: {side}
Entry: {fmt(entry)} | SL: {fmt(stop)}
TP1: {fmt(tp1)} | TP2: {fmt(tp2)}
POC: {fmt(poc)} | VAH: {fmt(vah)} | VAL: {fmt(val)}
Vol barra: {fmt(vol_bar)} (media {fmt(vol_avg)}) | Vol24h: {fmt(vol_glob,0)}
Rischio: {fmt(risk_pct*CAPITALE)} | Size: {fmt(size,4)} {symbol.replace("USDT","")}
Potenziale: {fmt(profit)} | R:R = {fmt(rr,2)}{note}
""".strip()

# ==========================
# LOOP PRINCIPALE
# ==========================
print("🚀 BOT AVVIATO – (MEXC) BTC/ETH | 15m+30m | ✅Acceptance + ⚡Spike | Volume Profile | Telegram (grafici) | Heartbeat (ora IT)")

while True:
    try:
        results = []         # per acceptance + livelli
        levels_map = {}
        news_flags = {}
        cmc_map = {}
        df_map = {}

        # Volumi globali (cache 10 min)
        for sym in SYMBOLS:
            root = sym.replace("USDT", "")
            cmc_map[root] = get_global_volume(root)

        # Dati per ciascun symbol/TF
        for sym in SYMBOLS:
            for tf in TIMEFRAMES:
                try:
                    df = get_ohlcv(sym, tf)
                    df_map[(sym, tf)] = df.copy()
                    poc, vah, val = build_volume_profile(df, bins=BINS_PROFILE)
                    if any(v is None for v in [poc, vah, val]):
                        continue
                    last_close = float(df["close"].iloc[-1])

                    # Acceptance
                    vw = TF_SETTINGS[tf]["vol_window"]
                    vm = TF_SETTINGS[tf]["vol_mult"]
                    acc = acceptance_check(df, vah, val, vw, vm)

                    # Spike detector (sul TF corrente; useremo 15m per il trigger)
                    spk = spike_check(df, vah, val, vw)

                    news_mode = volatility_spike_flag(df, NEWS_SPIKE_MULT)

                    levels_map[(sym, tf)] = {"poc": poc, "vah": vah, "val": val, "close": last_close}
                    news_flags[(sym, tf)] = news_mode

                    side_acc = None
                    if acc and acc["long"]:
                        side_acc = "BUY"
                    elif acc and acc["short"]:
                        side_acc = "SELL"

                    results.append({
                        "symbol": sym, "tf": tf, "side_acc": side_acc, "spike": spk,
                        "poc": poc, "vah": vah, "val": val, "close": last_close,
                        "vol_bar": acc["last_vol"] if acc else 0.0,
                        "vol_avg": acc["avg_vol"] if acc else 0.0,
                        "news": news_mode
                    })
                except Exception as e:
                    print(f"Errore {sym}-{tf}:", e)

        # ===== 1) Segnali ACCEPTANCE (multi-TF confermati) =====
        for sym in SYMBOLS:
            sym_res = [r for r in results if r["symbol"] == sym and r["side_acc"]]
            if not sym_res:
                continue
            sides = set(r["side_acc"] for r in sym_res)
            if len(sides) != 1 or len(sym_res) < len(TIMEFRAMES):
                continue  # niente conferma multi-TF

            side = sides.pop()
            r_fast = [r for r in sym_res if r["tf"] == "15m"][0]
            r_slow = [r for r in sym_res if r["tf"] == "30m"][0]
            entry = r_fast["close"]
            poc = r_fast["poc"]; vah = r_fast["vah"]; val = r_fast["val"]

            if side == "BUY":
                stop = val
                tp1 = poc
                tp2 = vah + (vah - val)
            else:
                stop = vah
                tp1 = poc
                tp2 = val - (vah - val)

            risk_usd = CAPITALE * RISK_PERCENT_ACCEPTANCE
            size, profit, rr = rr_compute(entry, stop, tp2, risk_usd)
            if size is None or rr < RR_MIN_ACCEPTANCE:
                continue
            if not should_send_signal(sym, side, "ACCEPTANCE", entry, COOLDOWN_MIN):
                continue

            chart_png = make_chart_png(df_map[(sym, "15m")], sym, "15m", poc, vah, val)
            caption = signal_caption(
                symbol=sym, tfs_ok=["15m","30m"], side=side, kind="ACCEPTANCE",
                entry=entry, stop=stop, tp1=tp1, tp2=tp2, poc=poc, vah=vah, val=val,
                vol_bar=r_fast["vol_bar"], vol_avg=r_fast["vol_avg"],
                vol_glob=cmc_map[sym.replace("USDT","")],
                size=size, profit=profit, rr=rr
            )
            send_telegram_photo(caption, chart_png)
            print(caption)
            _last_any_signal = now_local()
            _last_no_signal_notice = now_local()

        # ===== 2) Segnali ⚡ SPIKE (solo TF 15m, e solo se non appena uscito un Acceptance) =====
        for sym in SYMBOLS:
            # priorità: se è appena partito un acceptance per questo symbol negli ultimi COOLDOWN_MIN min, salta lo spike
            recent_acc = any(k[0] == sym and k[2] == "ACCEPTANCE" and (now_local() - _last_signal[k][0]) < timedelta(minutes=COOLDOWN_MIN) for k in _last_signal)
            if recent_acc:
                continue

            r15 = next((r for r in results if r["symbol"] == sym and r["tf"] == "15m"), None)
            if not r15 or not r15["spike"]:
                continue

            spike = r15["spike"]
            side = spike["side"]
            entry = r15["close"]; poc = r15["poc"]; vah = r15["vah"]; val = r15["val"]

            if side == "BUY":
                stop = val
                tp1 = poc
                tp2 = max(vah + (vah - val), entry + (entry - stop))
            else:
                stop = vah
                tp1 = poc
                tp2 = min(val - (vah - val), entry - (stop - entry))

            risk_usd = CAPITALE * RISK_PERCENT_SPIKE
            size, profit, rr = rr_compute(entry, stop, tp2, risk_usd)
            if size is None or rr < RR_MIN_SPIKE:
                continue
            if not should_send_signal(sym, side, "SPIKE", entry, COOLDOWN_MIN):
                continue

            chart_png = make_chart_png(df_map[(sym, "15m")], sym, "15m", poc, vah, val)
            caption = signal_caption(
                symbol=sym, tfs_ok=["15m"], side=side, kind="SPIKE",
                entry=entry, stop=stop, tp1=tp1, tp2=tp2, poc=poc, vah=vah, val=val,
                vol_bar=spike["last_vol"], vol_avg=spike["avg_vol"],
                vol_glob=cmc_map[sym.replace("USDT","")],
                size=size, profit=profit, rr=rr,
                extra_note=f"Spike: range {fmt(spike['rng_pct']*100,2)}% • vol ≥ {SPIKE_VOL_MULT}×"
            )
            send_telegram_photo(caption, chart_png)
            print(caption)
            _last_any_signal = now_local()
            _last_no_signal_notice = now_local()

        # Heartbeat
        if (now_local() - _last_heartbeat) >= timedelta(minutes=HEARTBEAT_MIN):
            hb = build_levels_report(levels_map, news_flags, cmc_map)
            send_telegram_text(hb); print(hb)
            _last_heartbeat = now_local()

        # Failsafe / Promemoria
        elapsed = now_local() - _last_any_signal
        if elapsed >= timedelta(hours=NO_SIGNAL_ALERT_HOURS):
            if (now_local() - _last_no_signal_notice) >= timedelta(hours=NO_SIGNAL_REMINDER_HOURS):
                warn = (f"⚠️ Nessun segnale valido da {int(elapsed.total_seconds()//3600)}h – "
                        f"mercato probabilmente in bilanciamento. "
                        f"Promemoria ogni {NO_SIGNAL_REMINDER_HOURS}h finché non arriva un segnale.")
                send_telegram_text(warn); print(warn)
                _last_no_signal_notice = now_local()

        time.sleep(30)

    except Exception as e:
        print("Errore loop principale:", e)
        time.sleep(5)
