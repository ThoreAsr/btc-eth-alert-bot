import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta

# ZoneInfo con fallback per ambienti <3.9
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    from backports.zoneinfo import ZoneInfo  # fallback per <3.9

# ==========================
# CONFIG
# ==========================
CAPITALE = 2000
RISK_PERCENT = 0.01                  # 1% per trade
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
TIMEFRAMES = ["15m", "30m"]

# Filtri volume dinamici per TF
TF_SETTINGS = {
    "15m": {"vol_window": 10, "vol_mult": 1.10},
    "30m": {"vol_window": 20, "vol_mult": 1.20},
}

BINS_PROFILE = 60                    # risoluzione profilo volume (POC/VAH/VAL)
RR_MIN = 1.5                         # non inviare segnali con R:R < 1.5
COOLDOWN_MIN = 15                    # no duplicati entro 15 minuti
HEARTBEAT_MIN = 30                   # report livelli ogni 30 minuti
NEWS_SPIKE_MULT = 2.5                # range barra > 2.5x media => NEWS MODE
NO_SIGNAL_ALERT_HOURS = 36           # failsafe: alert se zero segnali per 36h

# CoinMarketCap (volumi globali)
CMC_API_KEY = "e1bf46bf-1e42-4c30-8847-c011f772dcc8"
CMC_REFRESH_SEC = 600                # cache CMC 10 minuti

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

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print("Errore invio Telegram:", e)

# ==========================
# DATA
# ==========================
def get_ohlcv(symbol="BTCUSDT", interval="15m", limit=300):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "time","open","high","low","close","volume","c1","c2","c3","c4","c5","c6"
    ])
    # timestamps locali IT
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
        r = requests.get(url, headers=headers, timeout=10)
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

_last_signal = {}  # (symbol, side) -> (ts, entry)
def should_send_signal(symbol: str, side: str, entry: float, cooldown_min=COOLDOWN_MIN, tol=0.002):
    key = (symbol, side)
    last = _last_signal.get(key)
    now = now_local()
    if last:
        ts, last_entry = last
        if (now - ts) < timedelta(minutes=cooldown_min) and abs(entry - last_entry) / entry < tol:
            return False
    _last_signal[key] = (now, entry)
    return True

# Stato heartbeat e segnali
_last_heartbeat   = now_local() - timedelta(minutes=HEARTBEAT_MIN+1)
_last_any_signal  = now_local() - timedelta(hours=NO_SIGNAL_ALERT_HOURS+1)

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

def signal_message(symbol, tfs_ok, side, entry, stop, tp1, tp2, poc, vah, val, vol_bar, vol_avg, vol_glob, size, profit, rr, news_mode):
    news = "\n⚠️ NEWS MODE: volatilità anomala, rischio elevato." if news_mode else ""
    return f"""
=============================
🚨 SIGNAL {side} – {symbol}
=============================
⏰ {ts_label()}
TF confermati: {", ".join(tfs_ok)}
Entry: {fmt(entry)}
SL: {fmt(stop)}
TP1: {fmt(tp1)}
TP2: {fmt(tp2)}
POC: {fmt(poc)} | VAH: {fmt(vah)} | VAL: {fmt(val)}
Volume barra: {fmt(vol_bar)} (media {fmt(vol_avg)})
Volume globale 24h: {fmt(vol_glob,0)}
Rischio: {fmt(CAPITALE*RISK_PERCENT)}
Size: {fmt(size,4)} {symbol.replace("USDT","")}
Profitto pot.: {fmt(profit)}
R:R = {fmt(rr,2)}{news}
=============================
""".strip()

# ==========================
# LOOP PRINCIPALE
# ==========================
print("🚀 BOT AVVIATO – BTC/ETH | 15m+30m | Volume Profile | Volumi dinamici | Telegram | Heartbeat (ora IT)")

while True:
    try:
        results = []
        levels_map = {}
        news_flags = {}
        cmc_map = {}

        # Volumi globali (cache 10 min)
        for sym in SYMBOLS:
            root = sym.replace("USDT", "")
            cmc_map[root] = get_global_volume(root)

        # Dati per ciascun symbol/TF
        for sym in SYMBOLS:
            for tf in TIMEFRAMES:
                try:
                    df = get_ohlcv(sym, tf)
                    poc, vah, val = build_volume_profile(df, bins=BINS_PROFILE)
                    if any(v is None for v in [poc, vah, val]):
                        continue
                    last_close = float(df["close"].iloc[-1])

                    vw = TF_SETTINGS[tf]["vol_window"]
                    vm = TF_SETTINGS[tf]["vol_mult"]

                    acc = acceptance_check(df, vah, val, vw, vm)
                    news_mode = volatility_spike_flag(df, NEWS_SPIKE_MULT)

                    levels_map[(sym, tf)] = {"poc": poc, "vah": vah, "val": val, "close": last_close}
                    news_flags[(sym, tf)] = news_mode

                    side = None
                    if acc and acc["long"]:
                        side = "BUY"
                    elif acc and acc["short"]:
                        side = "SELL"

                    results.append({
                        "symbol": sym, "tf": tf, "side": side,
                        "poc": poc, "vah": vah, "val": val, "close": last_close,
                        "vol_bar": acc["last_vol"] if acc else 0.0,
                        "vol_avg": acc["avg_vol"] if acc else 0.0,
                        "news": news_mode
                    })
                except Exception as e:
                    print(f"Errore {sym}-{tf}:", e)

        # Conferma multi-TF e segnali
        for sym in SYMBOLS:
            sym_res = [r for r in results if r["symbol"] == sym and r["side"]]
            if not sym_res:
                continue
            sides = set(r["side"] for r in sym_res)
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

            risk_usd = CAPITALE * RISK_PERCENT
            size, profit, rr = rr_compute(entry, stop, tp2, risk_usd)
            if size is None or rr < RR_MIN:
                continue
            if not should_send_signal(sym, side, entry, COOLDOWN_MIN):
                continue

            news_mode = (r_fast["news"] or r_slow["news"])
            msg = signal_message(
                symbol=sym, tfs_ok=[r_fast["tf"], r_slow["tf"]], side=side,
                entry=entry, stop=stop, tp1=tp1, tp2=tp2,
                poc=poc, vah=vah, val=val,
                vol_bar=r_fast["vol_bar"], vol_avg=r_fast["vol_avg"],
                vol_glob=cmc_map[sym.replace("USDT","")],
                size=size, profit=profit, rr=rr, news_mode=news_mode
            )
            print(msg); send_telegram(msg)
            _last_any_signal = now_local()

        # Heartbeat
        if (now_local() - _last_heartbeat) >= timedelta(minutes=HEARTBEAT_MIN):
            hb = build_levels_report(levels_map, news_flags, cmc_map)
            print(hb); send_telegram(hb)
            _last_heartbeat = now_local()

        # Failsafe
        if (now_local() - _last_any_signal) >= timedelta(hours=NO_SIGNAL_ALERT_HOURS):
            warn = f"⚠️ Nessun segnale valido da {NO_SIGNAL_ALERT_HOURS}h – mercato probabilmente in bilanciamento."
            print(warn); send_telegram(warn)
            _last_any_signal = now_local()

        time.sleep(30)

    except Exception as e:
        print("Errore loop principale:", e)
        time.sleep(5)
