#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BOT FAMIGLIA — Watch-friendly + Volumetrica + Grafico + Piano Operativo
Anti-429 edition: cache interna, jitter e backoff.

- Prezzo/candele: MEXC primaria, Binance fallback (mirror + vision)
- Volumi 24h: CoinMarketCap (CMC) (cache 10 min)
- Volumetrica 15m: ultimo volume vs media 20 (↑ forte / ↑ / ≈ / ↓)
- Trend: EMA(15) vs EMA(50) su 15m e 30m
- Livelli: max/min ultime 48 candele 15m (~12h)
- Alert: SOLO su breakout/breakdown reali (heartbeat compatto opzionale)
- Grafico: auto su breakout/breakdown e/o spike “↑ forte”, con cooldown
- Piano operativo: LONG/SHORT con ingresso, STOP, TP1, TP2, LEVA
- Anti-rate limit: cache per klines 15m/30m, CMC; jitter random e backoff su 429

ENV obbligatorie:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID      (-100..., oppure più ID separati da virgola)
  CMC_API_KEY           (se assente i 24h saranno "n/d")

ENV consigliate:
  LOOP_SECONDS=180
  SYMBOLS=BTCUSDT,ETHUSDT
  SEND_HEARTBEAT=false
  INTERVAL_MINUTES=15
  CHART_ON_BREAKOUT=true
  CHART_ON_SPIKE=true
  CHART_COOLDOWN_MIN=30
  DEFAULT_LEVERAGE=3
  CAPITAL_USD=0
  RISK_PER_TRADE_PCT=0
"""

import os, io, time, random
from typing import List, Tuple, Dict, Optional
import requests

# ---------- ENV ----------
def env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, str(default)).strip().lower()
    return v in ("1", "true", "yes", "y", "on")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
CMC_API_KEY        = os.environ.get("CMC_API_KEY", "")

SYMBOLS         = [s.strip().upper() for s in os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
LOOP_SECONDS    = int(os.environ.get("LOOP_SECONDS", "180"))  # default 3m per anti-429
SEND_HEARTBEAT  = env_bool("SEND_HEARTBEAT", False)
INTERVAL_MIN    = int(os.environ.get("INTERVAL_MINUTES", "15"))

CHART_ON_BREAKOUT   = env_bool("CHART_ON_BREAKOUT", True)
CHART_ON_SPIKE      = env_bool("CHART_ON_SPIKE", True)
CHART_COOLDOWN_MIN  = int(os.environ.get("CHART_COOLDOWN_MIN", "30"))

DEFAULT_LEVERAGE    = float(os.environ.get("DEFAULT_LEVERAGE", "3"))
CAPITAL_USD         = float(os.environ.get("CAPITAL_USD", "0"))
RISK_PER_TRADE_PCT  = float(os.environ.get("RISK_PER_TRADE_PCT", "0"))

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nelle Environment Variables.")

# ---------- ENDPOINTS ----------
MEXC_BASES = [
    "https://api.mexc.com",
    "https://www.mexc.com"
]
BINANCE_BASES = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api-gcp.binance.com",
    "https://data-api.binance.vision"
]

# ---------- CACHE & RATE LIMIT ----------
CACHE: Dict[str, dict] = {
    # chiavi:
    # f"{symbol}_15m": {"ts": epoch, "data": klines}
    # f"{symbol}_30m": {"ts": epoch, "data": klines}
    # "CMC_VOL": {"ts": epoch, "data": {base:vol}}
}
TTL_15M = 300   # s, minimo 3 minuti per candele 15m
TTL_30M = 600   # s, minimo 6 minuti per candele 30m
TTL_CMC = 900   # s, 15 minuti

def jitter_sleep(min_s=0.3, max_s=0.9):
    time.sleep(random.uniform(min_s, max_s))

def http_get(url: str, params: dict, timeout=15, retries=3, backoff=2.0):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 429:
                # backoff su 429
                time.sleep((i+1) * backoff)
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep((i+1) * 0.5)
    if last:
        raise last

def _get_json_with_fallback(paths: List[tuple], params: dict, timeout=15):
    last_err = None
    for base, path in paths:
        try:
            jitter_sleep(0.15, 0.5)
            r = http_get(f"{base}{path}", params=params, timeout=timeout)
            return r.json()
        except Exception as e:
            last_err = e
            continue
    raise last_err

# ---------- FETCH ----------
def fetch_price(symbol: str) -> float:
    paths = [(b, "/api/v3/ticker/price") for b in MEXC_BASES] + \
            [(b, "/api/v3/ticker/price") for b in BINANCE_BASES]
    data = _get_json_with_fallback(paths, {"symbol": symbol}, timeout=8)
    return float(data["price"])

def fetch_klines_cached(symbol: str, interval: str, limit: int, ttl: int) -> list:
    key = f"{symbol}_{interval}"
    now = time.time()
    c = CACHE.get(key)
    if c and now - c["ts"] < ttl:
        return c["data"]
    paths = [(b, "/api/v3/klines") for b in MEXC_BASES] + \
            [(b, "/api/v3/klines") for b in BINANCE_BASES]
    data = _get_json_with_fallback(paths, {"symbol": symbol, "interval": interval, "limit": limit}, timeout=12)
    CACHE[key] = {"ts": now, "data": data}
    return data

def fetch_cmc_volumes_cached(symbols: List[str]) -> Dict[str, float]:
    now = time.time()
    c = CACHE.get("CMC_VOL")
    if c and now - c["ts"] < TTL_CMC:
        return c["data"]
    if not CMC_API_KEY:
        return {}
    bases = sorted({s.replace("USDT", "").replace("USD", "") for s in symbols})
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    jitter_sleep(0.2, 0.6)
    r = http_get(url, {"symbol": ",".join(bases), "convert": "USD"}, timeout=12)
    data = r.json().get("data", {})
    out: Dict[str, float] = {}
    for base in bases:
        try:
            out[base] = float(data[base][0]["quote"]["USD"]["volume_24h"])
        except Exception:
            pass
    CACHE["CMC_VOL"] = {"ts": now, "data": out}
    return out

# ---------- INDICATORS ----------
def ema(values: List[float], length: int) -> List[float]:
    if not values or length <= 0 or len(values) < length:
        return []
    k = 2 / (length + 1)
    ema_vals = [sum(values[:length]) / length]
    for v in values[length:]:
        ema_vals.append(v * k + ema_vals[-1] * (1 - k))
    pad = [None] * (len(values) - len(ema_vals))
    return pad + ema_vals

def trend_from_ema(closes: List[float], fast_len=15, slow_len=50) -> str:
    efast = ema(closes, fast_len)
    eslow = ema(closes, slow_len)
    if not efast or not eslow or efast[-1] is None or eslow[-1] is None:
        return "n/d"
    if efast[-1] > eslow[-1]: return "rialzo"
    if efast[-1] < eslow[-1]: return "ribasso"
    return "neutro"

def compute_levels(highs: List[float], lows: List[float], window=48) -> Tuple[float, float]:
    if len(highs) < window or len(lows) < window:
        window = min(len(highs), len(lows))
    return max(highs[-window:]), min(lows[-window:])

def volume_spike_15m(vols15: List[float], lookback=20) -> Tuple[float, str]:
    if len(vols15) < lookback + 1:
        return 0.0, "n/d"
    avg = sum(vols15[-lookback-1:-1]) / lookback
    last = vols15[-1]
    if avg <= 0: return 0.0, "n/d"
    pct = (last / avg - 1.0) * 100.0
    if pct >= 100:   label = "↑ forte"
    elif pct >= 25:  label = "↑"
    elif pct <= -25: label = "↓"
    else:            label = "≈"
    return pct, label

# ---------- FORMATTING ----------
def round_k(x: float) -> str:
    step = 100 if x >= 10000 else 50
    y = round(x / step) * step
    if y >= 1000:
        if y % 1000 == 0: return f"{int(y/1000)}k"
        return f"{y/1000:.1f}k"
    return f"{int(y)}"

def fmt_price(p: float) -> str:
    return f"{p:,.0f}$".replace(",", ".")

def fmt_billions(x: float) -> str:
    try: return f"{x/1e9:.1f}B"
    except Exception: return "n/d"

# ---------- OPERATIVE PLAN ----------
def op_plan_long(res: float, sup: float) -> Tuple[float, float, float, float]:
    entry = res
    stop  = sup * 0.998  # -0.2%
    R = max(entry - stop, 1e-6)
    return entry, stop, entry + R, entry + 2 * R

def op_plan_short(res: float, sup: float) -> Tuple[float, float, float, float]:
    entry = sup
    stop  = res * 1.002  # +0.2%
    R = max(stop - entry, 1e-6)
    return entry, stop, entry - R, entry - 2 * R

def sizing_line(entry: float, stop: float) -> str:
    if CAPITAL_USD > 0 and RISK_PER_TRADE_PCT > 0:
        risk_usd = CAPITAL_USD * (RISK_PER_TRADE_PCT / 100.0)
        per_unit = abs(entry - stop)
        if per_unit <= 0: return ""
        qty = risk_usd / per_unit
        return f"💼 Rischio {RISK_PER_TRADE_PCT:.1f}% (~${risk_usd:.0f}) | Size≈ {qty:.4f}"
    return ""

# ---------- MESSAGES ----------
def build_alert(symbol: str, price: float, tr15: str, tr30: str,
                res: float, sup: float,
                vol_spike_pct: float, vol_spike_label: str,
                vol24h_usd: Optional[float]) -> str:
    v24 = fmt_billions(vol24h_usd) if vol24h_usd is not None else "n/d"
    eL, sL, t1L, t2L = op_plan_long(res, sup)
    eS, sS, t1S, t2S = op_plan_short(res, sup)
    size_note_long  = sizing_line(eL, sL)
    size_note_short = sizing_line(eS, sS)
    msg = (
        f"📉 {symbol}\n"
        f"💵 {fmt_price(price)}\n"
        f"📈 15m:{tr15} | 30m:{tr30}\n"
        f"🔑 R:{round_k(res)} | S:{round_k(sup)}\n"
        f"🔊 Vol15m: {vol_spike_label} ({vol_spike_pct:.0f}%) | 24h:{v24}\n"
        f"🟩 LONG >{round_k(eL)} | SL {fmt_price(sL)} | 🎯 {fmt_price(t1L)} / {fmt_price(t2L)} | ⚡x{int(DEFAULT_LEVERAGE)}"
    )
    if size_note_long:
        msg += f"\n{size_note_long}"
    msg += (
        f"\n🟥 SHORT <{round_k(eS)} | SL {fmt_price(sS)} | 🎯 {fmt_price(t1S)} / {fmt_price(t2S)} | ⚡x{int(DEFAULT_LEVERAGE)}"
    )
    if size_note_short:
        msg += f"\n{size_note_short}"
    return msg

def build_heartbeat(symbol: str, price: float, tr15: str, tr30: str,
                    res: float, sup: float, vol_spike_label: str) -> str:
    return (
        f"🫀 {symbol}  {fmt_price(price)}\n"
        f"15m:{tr15}/30m:{tr30}  R:{round_k(res)} S:{round_k(sup)}  🔊{vol_spike_label}"
    )

# ---------- TELEGRAM ----------
def get_chat_ids() -> List[str]:
    return [cid.strip() for cid in TELEGRAM_CHAT_ID.strip().split(",") if cid.strip()]

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in get_chat_ids():
        requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=15).raise_for_status()

# --- sendPhoto (grafico) ---
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def send_photo(image_bytes: bytes, caption: str = ""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    for chat_id in get_chat_ids():
        files = {"photo": ("chart.png", image_bytes)}
        data = {"chat_id": chat_id, "caption": caption}
        requests.post(url, data=data, files=files, timeout=30).raise_for_status()

def make_chart_png(symbol: str, k15: list, res: float, sup: float, price: float) -> bytes:
    closes = [float(k[4]) for k in k15][-100:]
    xs = list(range(len(closes)))
    plt.figure(figsize=(6, 3), dpi=200)
    plt.plot(xs, closes)
    plt.axhline(res, linestyle="--")
    plt.axhline(sup, linestyle="--")
    plt.title(f"{symbol}  |  {fmt_price(price)}")
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf.read()

# ---------- STATE ----------
class State:
    def __init__(self):
        self.last_side: Dict[str, str] = {}
        self.last_hb_minute: int = -1
        self.init_sent: Dict[str, bool] = {}
        self.last_chart_ts: Dict[str, float] = {}

STATE = State()

def side_vs_band(price: float, sup: float, res: float) -> str:
    if price > res: return "above"
    if price < sup: return "below"
    return "between"

# ---------- CORE ----------
def process_symbol(symbol: str, cmc_vols: Dict[str, float]):
    # Klines con cache (anti-429)
    k15 = fetch_klines_cached(symbol, "15m", 200, TTL_15M)
    jitter_sleep(0.05, 0.2)
    k30 = fetch_klines_cached(symbol, "30m", 200, TTL_30M)

    closes15 = [float(k[4]) for k in k15]
    highs15  = [float(k[2]) for k in k15]
    lows15   = [float(k[3]) for k in k15]
    vols15   = [float(k[5]) for k in k15]
    closes30 = [float(k[4]) for k in k30]

    res, sup = compute_levels(highs15, lows15, 48)
    tr15 = trend_from_ema(closes15, 15, 50)
    tr30 = trend_from_ema(closes30, 15, 50)

    jitter_sleep(0.05, 0.2)
    price = fetch_price(symbol)

    spike_pct, spike_label = volume_spike_15m(vols15, 20)
    base = symbol.replace("USDT", "").replace("USD", "")
    vol24h = cmc_vols.get(base)

    now_side = side_vs_band(price, sup, res)
    prev_side = STATE.last_side.get(symbol, "between")
    STATE.last_side[symbol] = now_side

    # Heartbeat compatto (se attivo)
    if SEND_HEARTBEAT:
        now_min = int(time.time() // 60)
        if now_min % INTERVAL_MIN == 0 and STATE.last_hb_minute != now_min:
            STATE.last_hb_minute = now_min
            send_telegram(build_heartbeat(symbol, price, tr15, tr30, res, sup, spike_label))

    # Alert testuale su cambi di stato (breakout/breakdown)
    fired_breakout = False
    fired = False
    if prev_side != now_side:
        send_telegram(build_alert(symbol, price, tr15, tr30, res, sup, spike_pct, spike_label, vol24h))
        fired_breakout = True
        fired = True

    # Primo messaggio all’avvio
    if not STATE.init_sent.get(symbol) and not fired:
        send_telegram(build_alert(symbol, price, tr15, tr30, res, sup, spike_pct, spike_label, vol24h))
        STATE.init_sent[symbol] = True

    # Grafico su condizioni + cooldown
    want_chart = False
    if CHART_ON_BREAKOUT and fired_breakout:
        want_chart = True
    if CHART_ON_SPIKE and spike_label == "↑ forte":
        want_chart = True

    if want_chart:
        now_ts = time.time()
        last_ts = STATE.last_chart_ts.get(symbol, 0.0)
        if now_ts - last_ts >= CHART_COOLDOWN_MIN * 60:
            try:
                img = make_chart_png(symbol, k15, res, sup, price)
                send_photo(img, caption=f"{symbol} | R:{round_k(res)} S:{round_k(sup)}")
                STATE.last_chart_ts[symbol] = now_ts
            except Exception:
                pass

def main_loop():
    while True:
        try:
            cmc_vols = fetch_cmc_volumes_cached(SYMBOLS)
            for s in SYMBOLS:
                process_symbol(s, cmc_vols)
        except requests.HTTPError as e:
            code = getattr(e.response, "status_code", None)
            # Silenzia 429/451; logga solo altri errori
            if code not in (429, 451):
                try:
                    send_telegram(f"⚠️ Errore dati: HTTP {code or ''}".strip())
                except Exception:
                    pass
        except Exception:
            # Silenzioso: niente allegati
            pass
        time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main_loop()
