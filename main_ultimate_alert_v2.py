#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BOT FAMIGLIA — Apple Watch friendly + Volumetrica
- Prezzo/candle: MEXC primaria, Binance fallback (con mirror) + vision
- Volumi 24h: CoinMarketCap (CMC)
- Segnale volumetrico: volume ultima 15m vs media 20 (↑ forte / ↑ / ≈ / ↓)
- Trend: EMA(15) vs EMA(50) su 15m e 30m
- Livelli: max/min ultime 48 candele 15m (~12h)
- Alert: solo su breakout/breakdown reali (con opzionale heartbeat compatto)

ENV (Render → Environment):
  TELEGRAM_BOT_TOKEN = <token>
  TELEGRAM_CHAT_ID   = -100xxxxxxxxxx
  CMC_API_KEY        = <la tua CMC key>   # e1bf46bf-1e42-4c30-8847-c011f772dcc8
Opzionali:
  SYMBOLS            = BTCUSDT,ETHUSDT
  LOOP_SECONDS       = 60
  SEND_HEARTBEAT     = false
  INTERVAL_MINUTES   = 15
"""

import os
import time
from typing import List, Tuple, Dict
import requests

# --------- ENV ----------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
CMC_API_KEY        = os.environ.get("CMC_API_KEY", "")

def env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, str(default)).strip().lower()
    return v in ("1","true","yes","y","on")

SYMBOLS         = [s.strip().upper() for s in os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
LOOP_SECONDS    = int(os.environ.get("LOOP_SECONDS", "60"))
SEND_HEARTBEAT  = env_bool("SEND_HEARTBEAT", False)
INTERVAL_MIN    = int(os.environ.get("INTERVAL_MINUTES", "15"))

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nelle Environment Variables.")
if not CMC_API_KEY:
    # Non blocchiamo l’avvio: i volumi 24h verranno marcati come n/d
    pass

# --------- ENDPOINTS FALLBACK ----------
MEXC_BASES = [
    "https://api.mexc.com",           # primaria
    "https://www.mexc.com"            # backup (spesso proxata)
]
BINANCE_BASES = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api-gcp.binance.com",
    "https://data-api.binance.vision" # mirror pubblico
]

def _get_json_with_fallback(paths: List[tuple], params: dict, timeout=15):
    """
    paths: lista di tuple (base_url, path)
    prova in ordine finché uno risponde 2xx
    """
    last_err = None
    for base, path in paths:
        try:
            r = requests.get(f"{base}{path}", params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            continue
    raise last_err

# --------- FETCHERS ----------
def fetch_price(symbol: str) -> float:
    # MEXC
    mx_paths = [(b, "/api/v3/ticker/price") for b in MEXC_BASES]
    # Binance fallback
    bz_paths = [(b, "/api/v3/ticker/price") for b in BINANCE_BASES]
    data = _get_json_with_fallback(mx_paths + bz_paths, {"symbol": symbol}, timeout=10)
    return float(data["price"])

def fetch_klines(symbol: str, interval: str, limit: int = 200) -> list:
    # MEXC
    mx_paths = [(b, "/api/v3/klines") for b in MEXC_BASES]
    # Binance fallback
    bz_paths = [(b, "/api/v3/klines") for b in BINANCE_BASES]
    return _get_json_with_fallback(mx_paths + bz_paths,
                                   {"symbol": symbol, "interval": interval, "limit": limit},
                                   timeout=15)

def fetch_cmc_volumes(symbols: List[str]) -> Dict[str, float]:
    """
    symbols: es. ["BTCUSDT","ETHUSDT"] -> estraiamo "BTC","ETH"
    ritorna: {"BTC": vol24h_usd, "ETH": vol24h_usd}
    """
    if not CMC_API_KEY:
        return {}
    # dedup delle base-coin
    bases = sorted({s.replace("USDT","").replace("USD","") for s in symbols})
    qs = ",".join(bases)
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    r = requests.get(url, params={"symbol": qs, "convert": "USD"}, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json().get("data", {})
    out = {}
    for base in bases:
        try:
            item = data[base][0]["quote"]["USD"]["volume_24h"]
            out[base] = float(item)
        except Exception:
            pass
    return out

# --------- INDICATORS ----------
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
    if efast[-1] > eslow[-1]:
        return "rialzo"
    if efast[-1] < eslow[-1]:
        return "ribasso"
    return "neutro"

def compute_levels(highs: List[float], lows: List[float], window=48) -> Tuple[float,float]:
    if len(highs) < window or len(lows) < window:
        window = min(len(highs), len(lows))
    return max(highs[-window:]), min(lows[-window:])

def volume_spike_15m(vols15: List[float], lookback=20) -> Tuple[float, str]:
    """
    ritorna (percent_spike, label)
    percent_spike = (last / avg_20 - 1) * 100
    label: "↑ forte" se >= +100%, "↑" se +25..100, "≈" se -25..+25, "↓" se < -25
    """
    if len(vols15) < lookback+1:
        return 0.0, "n/d"
    avg = sum(vols15[-lookback-1:-1]) / lookback
    last = vols15[-1]
    if avg <= 0:
        return 0.0, "n/d"
    pct = (last/avg - 1.0) * 100.0
    if pct >= 100:
        label = "↑ forte"
    elif pct >= 25:
        label = "↑"
    elif pct <= -25:
        label = "↓"
    else:
        label = "≈"
    return pct, label

# --------- FORMATTING ----------
def round_k(x: float) -> str:
    step = 100 if x >= 10000 else 50
    y = round(x/step)*step
    if y >= 1000:
        if y % 1000 == 0:
            return f"{int(y/1000)}k"
        return f"{y/1000:.1f}k"
    return f"{int(y)}"

def fmt_price(p: float) -> str:
    return f"{p:,.0f}$".replace(",", ".")

def fmt_billions(x: float) -> str:
    # 75.6B stile compatto
    try:
        return f"{x/1e9:.1f}B"
    except Exception:
        return "n/d"

def build_alert(symbol: str, price: float, tr15: str, tr30: str,
                res: float, sup: float,
                vol_spike_pct: float, vol_spike_label: str,
                vol24h_usd: float|None) -> str:
    v24 = fmt_billions(vol24h_usd) if vol24h_usd is not None else "n/d"
    return (
        f"🚨 {symbol}\n"
        f"💵 {fmt_price(price)}\n"
        f"📈 15m:{tr15} | 30m:{tr30}\n"
        f"🔑 R:{round_k(res)} | S:{round_k(sup)}\n"
        f"🔊 Vol15m: {vol_spike_label} ({vol_spike_pct:.0f}%) | 24h:{v24}\n"
        f"👉 Buy >{round_k(res)} | Sell <{round_k(sup)}"
    )

def build_heartbeat(symbol: str, price: float, tr15: str, tr30: str,
                    res: float, sup: float,
                    vol_spike_label: str) -> str:
    return (
        f"🫀 {symbol}  {fmt_price(price)}\n"
        f"15m:{tr15}/30m:{tr30}  R:{round_k(res)} S:{round_k(sup)}  🔊{vol_spike_label}"
    )

# --------- TELEGRAM ----------
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15).raise_for_status()

# --------- STATE ----------
class State:
    def __init__(self):
        self.last_side: Dict[str,str] = {}
        self.last_hb_minute: int = -1
        self.init_sent: Dict[str,bool] = {}

STATE = State()

def side_vs_band(price: float, sup: float, res: float) -> str:
    if price > res: return "above"
    if price < sup: return "below"
    return "between"

# --------- CORE ----------
def process_symbol(symbol: str, cmc_vols: Dict[str, float]):
    # 15m e 30m
    k15 = fetch_klines(symbol, "15m", 200)
    k30 = fetch_klines(symbol, "30m", 200)

    closes15 = [float(k[4]) for k in k15]
    highs15  = [float(k[2]) for k in k15]
    lows15   = [float(k[3]) for k in k15]
    vols15   = [float(k[5]) for k in k15]   # volume base-asset

    closes30 = [float(k[4]) for k in k30]

    res, sup = compute_levels(highs15, lows15, 48)
    tr15 = trend_from_ema(closes15, 15, 50)
    tr30 = trend_from_ema(closes30, 15, 50)
    price = fetch_price(symbol)
    spike_pct, spike_label = volume_spike_15m(vols15, 20)

    base = symbol.replace("USDT","").replace("USD","")
    vol24h = cmc_vols.get(base)

    now_side = side_vs_band(price, sup, res)
    prev_side = STATE.last_side.get(symbol, "between")
    STATE.last_side[symbol] = now_side

    # Heartbeat (se attivo)
    if SEND_HEARTBEAT:
        now_min = int(time.time() // 60)
        if now_min % INTERVAL_MIN == 0 and STATE.last_hb_minute != now_min:
            STATE.last_hb_minute = now_min
            send_telegram(build_heartbeat(symbol, price, tr15, tr30, res, sup, spike_label))

    fired = False
    if prev_side != now_side:
        send_telegram(build_alert(symbol, price, tr15, tr30, res, sup, spike_pct, spike_label, vol24h))
        fired = True

    # 1° messaggio di setup all’avvio
    if not STATE.init_sent.get(symbol) and not fired:
        send_telegram(build_alert(symbol, price, tr15, tr30, res, sup, spike_pct, spike_label, vol24h))
        STATE.init_sent[symbol] = True

def main_loop():
    while True:
        try:
            cmc_vols = fetch_cmc_volumes(SYMBOLS)
            for s in SYMBOLS:
                process_symbol(s, cmc_vols)
        except Exception as e:
            try:
                send_telegram(f"⚠️ Errore dati: {type(e).__name__}")
            except Exception:
                pass
        time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main_loop()
