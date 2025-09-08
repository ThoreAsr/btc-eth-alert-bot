#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BOT FAMIGLIA — TOP edition
Watch-friendly + Volumetrica + RSI + Grafico + Piano operativo + Entrate/Uscite
Anti-429 + Fix CMC headers (401) + avvio/avviso rate-limit.

- Prezzo/candele: MEXC primaria, Binance fallback (mirror + vision)
- Volumi 24h: CoinMarketCap (CMC) (cache 15 min)
- Volumetrica 15m: ultimo volume vs media 20 (↑ forte / ↑ / ≈ / ↓)
- Trend: EMA(15) vs EMA(50) su 15m e 30m
- RSI(14) su 15m come conferma (configurabile)
- Livelli: max/min ultime 48 candele 15m (~12h)
- Piano operativo: LONG/SHORT con ingresso, STOP, TP1, TP2, LEVA
- Alert:
    • Setup (plan) su cambi di stato banda R/S
    • ENTRATA quando il prezzo supera il trigger (con conferme)
    • USCITA su TP1/TP2/SL (no spam, con stato)
- Grafico: auto su breakout/spike/entrate, con cooldown
- Anti-rate limit: cache interna, jitter, backoff, avviso 429/451 max 1x/10min
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
LOOP_SECONDS    = int(os.environ.get("LOOP_SECONDS", "240"))
SEND_HEARTBEAT  = env_bool("SEND_HEARTBEAT", False)
INTERVAL_MIN    = int(os.environ.get("INTERVAL_MINUTES", "15"))

CHART_ON_BREAKOUT   = env_bool("CHART_ON_BREAKOUT", True)
CHART_ON_SPIKE      = env_bool("CHART_ON_SPIKE", True)
CHART_COOLDOWN_MIN  = int(os.environ.get("CHART_COOLDOWN_MIN", "30"))

DEFAULT_LEVERAGE    = float(os.environ.get("DEFAULT_LEVERAGE", "3"))
CAPITAL_USD         = float(os.environ.get("CAPITAL_USD", "0"))
RISK_PER_TRADE_PCT  = float(os.environ.get("RISK_PER_TRADE_PCT", "0"))

# RSI (nuovo)
RSI_CONFIRMATION    = env_bool("RSI_CONFIRMATION", True)
RSI_LONG_MIN        = float(os.environ.get("RSI_LONG_MIN", "55"))
RSI_SHORT_MAX       = float(os.environ.get("RSI_SHORT_MAX", "45"))

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nelle Environment.")

# ---------- ENDPOINTS ----------
MEXC_BASES = ["https://api.mexc.com", "https://www.mexc.com"]
BINANCE_BASES = [
    "https://api.binance.com","https://api1.binance.com","https://api2.binance.com",
    "https://api3.binance.com","https://api-gcp.binance.com","https://data-api.binance.vision"
]

# ---------- CACHE & RATE LIMIT ----------
CACHE: Dict[str, dict] = {}
TTL_15M = 300   # 5 min
TTL_30M = 900   # 15 min
TTL_CMC = 900   # 15 min
LAST_RATE_WARN = {"ts": 0}

def jitter_sleep(a=0.3, b=0.9): time.sleep(random.uniform(a, b))

def http_get(url: str, params: dict, timeout=15, retries=3, backoff=2.0, headers=None):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep((i+1) * backoff); continue
            r.raise_for_status(); return r
        except Exception as e:
            last = e; time.sleep((i+1)*0.5)
    if last: raise last

def _get_json_with_fallback(paths: List[tuple], params: dict, timeout=15):
    last_err = None
    for base, path in paths:
        try:
            jitter_sleep(0.15,0.5)
            r = http_get(f"{base}{path}", params=params, timeout=timeout)
            return r.json()
        except Exception as e:
            last_err = e
    raise last_err

# ---------- FETCH ----------
def fetch_price(symbol: str) -> float:
    paths = [(b,"/api/v3/ticker/price") for b in MEXC_BASES] + [(b,"/api/v3/ticker/price") for b in BINANCE_BASES]
    data = _get_json_with_fallback(paths, {"symbol": symbol}, timeout=8)
    return float(data["price"])

def fetch_klines_cached(symbol: str, interval: str, limit: int, ttl: int) -> list:
    key = f"{symbol}_{interval}"; now = time.time()
    c = CACHE.get(key)
    if c and now - c["ts"] < ttl: return c["data"]
    paths = [(b,"/api/v3/klines") for b in MEXC_BASES] + [(b,"/api/v3/klines") for b in BINANCE_BASES]
    data = _get_json_with_fallback(paths, {"symbol": symbol,"interval": interval,"limit": limit}, timeout=12)
    CACHE[key] = {"ts": now, "data": data}; return data

def fetch_cmc_volumes_cached(symbols: List[str]) -> Dict[str, float]:
    now = time.time(); c = CACHE.get("CMC_VOL")
    if c and now - c["ts"] < TTL_CMC: return c["data"]
    if not CMC_API_KEY: return {}
    try:
        bases = sorted({s.replace("USDT","").replace("USD","") for s in symbols})
        url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
        headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
        jitter_sleep(0.2,0.6)
        r = http_get(url, {"symbol": ",".join(bases), "convert":"USD"}, timeout=12, headers=headers)
        data = r.json().get("data", {}); out: Dict[str,float] = {}
        for base in bases:
            try: out[base] = float(data[base][0]["quote"]["USD"]["volume_24h"])
            except Exception: pass
        CACHE["CMC_VOL"] = {"ts": now, "data": out}; return out
    except Exception:
        return c["data"] if c else {}

# ---------- INDICATORS ----------
def ema(values: List[float], length: int) -> List[float]:
    if not values or length<=0 or len(values)<length: return []
    k = 2/(length+1); ema_vals=[sum(values[:length])/length]
    for v in values[length:]: ema_vals.append(v*k + ema_vals[-1]*(1-k))
    return [None]*(len(values)-len(ema_vals)) + ema_vals

def trend_from_ema(closes: List[float], fast=15, slow=50) -> str:
    efast, eslow = ema(closes, fast), ema(closes, slow)
    if not efast or not eslow or efast[-1] is None or eslow[-1] is None: return "n/d"
    return "rialzo" if efast[-1] > eslow[-1] else ("ribasso" if efast[-1] < eslow[-1] else "neutro")

def compute_levels(highs: List[float], lows: List[float], window=48) -> Tuple[float,float]:
    if len(highs)<window or len(lows)<window: window=min(len(highs),len(lows))
    return max(highs[-window:]), min(lows[-window:])

def rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1: return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = values[i] - values[i-1]
        if diff >= 0: gains += diff
        else: losses -= diff
    if losses == 0: return 100.0
    rs = (gains/period) / (losses/period)
    return 100 - (100/(1+rs))

def volume_spike_15m(vols15: List[float], lookback=20) -> Tuple[float,str]:
    if len(vols15) < lookback+1: return 0.0,"n/d"
    avg = sum(vols15[-lookback-1:-1])/lookback; last = vols15[-1]
    if avg<=0: return 0.0,"n/d"
    pct = (last/avg -1.0)*100.0
    if   pct>=100: label="↑ forte"
    elif pct>=25:  label="↑"
    elif pct<=-25: label="↓"
    else:          label="≈"
    return pct,label

# ---------- FORMAT ----------
def round_k(x: float)->str:
    step=100 if x>=10000 else 50; y=round(x/step)*step
    if y>=1000: return f"{int(y/1000)}k" if y%1000==0 else f"{y/1000:.1f}k"
    return f"{int(y)}"

def fmt_price(p: float)->str: return f"{p:,.0f}$".replace(",",".")
def fmt_billions(x: float)->str:
    try: return f"{x/1e9:.1f}B"
    except Exception: return "n/d"

# ---------- OPERATIVE PLAN ----------
def op_plan_long(res: float, sup: float)->Tuple[float,float,float,float]:
    entry=res; stop=sup*0.998; R=max(entry-stop,1e-6)
    return entry,stop,entry+R,entry+2*R

def op_plan_short(res: float, sup: float)->Tuple[float,float,float,float]:
    entry=sup; stop=res*1.002; R=max(stop-entry,1e-6)
    return entry,stop,entry-R,entry-2*R

def sizing_line(entry: float, stop: float)->str:
    if CAPITAL_USD>0 and RISK_PER_TRADE_PCT>0:
        risk=CAPITAL_USD*(RISK_PER_TRADE_PCT/100.0)
        per_unit=abs(entry-stop)
        if per_unit<=0: return ""
        qty=risk/per_unit
        return f"💼 Rischio {RISK_PER_TRADE_PCT:.1f}% (~${risk:.0f}) | Size≈ {qty:.4f}"
    return ""

# ---------- MESSAGES ----------
def build_setup(symbol, price, tr15, tr30, res, sup, sp_pct, sp_lbl, vol24h):
    v24 = fmt_billions(vol24h) if vol24h is not None else "n/d"
    eL,sL,t1L,t2L = op_plan_long(res, sup)
    eS,sS,t1S,t2S = op_plan_short(res, sup)
    sizeL, sizeS = sizing_line(eL,sL), sizing_line(eS,sS)
    msg = (f"📉 {symbol}\n"
           f"💵 {fmt_price(price)}\n"
           f"📈 15m:{tr15} | 30m:{tr30}\n"
           f"🔑 R:{round_k(res)} | S:{round_k(sup)}\n"
           f"🔊 Vol15m: {sp_lbl} ({sp_pct:.0f}%) | 24h:{v24}\n"
           f"🟩 LONG >{round_k(eL)} | SL {fmt_price(sL)} | 🎯 {fmt_price(t1L)} / {fmt_price(t2L)} | ⚡x{int(DEFAULT_LEVERAGE)}")
    if sizeL: msg += f"\n{sizeL}"
    msg += (f"\n🟥 SHORT <{round_k(eS)} | SL {fmt_price(sS)} | 🎯 {fmt_price(t1S)} / {fmt_price(t2S)} | ⚡x{int(DEFAULT_LEVERAGE)}")
    if sizeS: msg += f"\n{sizeS}"
    return msg

def build_heartbeat(symbol, price, tr15, tr30, res, sup, sp_lbl):
    return f"🫀 {symbol}  {fmt_price(price)}\n15m:{tr15}/30m:{tr30}  R:{round_k(res)} S:{round_k(sup)}  🔊{sp_lbl}"

def build_entry(symbol, side, entry, sl, tp1, tp2, price, rsi_v):
    side_emoji = "🟩 LONG" if side=="long" else "🟥 SHORT"
    rsi_txt = f" | RSI:{rsi_v:.0f}" if rsi_v is not None else ""
    return (f"🚀 ENTRA {side_emoji} {symbol}\n"
            f"💵 {fmt_price(price)}  | trigger {fmt_price(entry)}\n"
            f"🛡️ SL {fmt_price(sl)}  🎯 {fmt_price(tp1)} / {fmt_price(tp2)}  ⚡x{int(DEFAULT_LEVERAGE)}{rsi_txt}")

def build_exit(symbol, reason, price):
    return f"✅ USCITA {symbol} — {reason} a {fmt_price(price)}"

# ---------- TELEGRAM ----------
def get_chat_ids()->List[str]:
    return [cid.strip() for cid in TELEGRAM_CHAT_ID.strip().split(",") if cid.strip()]

def send_telegram(text: str):
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for cid in get_chat_ids():
        requests.post(url, data={"chat_id": cid, "text": text}, timeout=15).raise_for_status()

# --- sendPhoto ---
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def send_photo(image_bytes: bytes, caption: str=""):
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    for cid in get_chat_ids():
        files={"photo":("chart.png", image_bytes)}
        data={"chat_id":cid,"caption":caption}
        requests.post(url, data=data, files=files, timeout=30).raise_for_status()

def make_chart_png(symbol, k15, res, sup, price)->bytes:
    closes=[float(k[4]) for k in k15][-100:]; xs=list(range(len(closes)))
    plt.figure(figsize=(6,3), dpi=200)
    plt.plot(xs, closes); plt.axhline(res, linestyle="--"); plt.axhline(sup, linestyle="--")
    plt.title(f"{symbol}  |  {fmt_price(price)}"); plt.tight_layout()
    buf=io.BytesIO(); plt.savefig(buf, format="png"); plt.close(); buf.seek(0)
    return buf.read()

# ---------- STATE ----------
class Position:
    def __init__(self):
        self.side: Optional[str] = None   # "long"/"short"/None
        self.entry: float = 0.0
        self.sl: float = 0.0
        self.tp1: float = 0.0
        self.tp2: float = 0.0
        self.hit_tp1: bool = False
        self.last_entry_ts: float = 0.0   # throttle

class State:
    def __init__(self):
        self.last_side: Dict[str,str] = {}
        self.last_hb_minute: int = -1
        self.init_sent: Dict[str,bool] = {}
        self.last_chart_ts: Dict[str,float] = {}
        self.pos: Dict[str,Position] = {}

STATE = State()

def side_vs_band(price,sup,res)->str:
    if price>res: return "above"
    if price<sup: return "below"
    return "between"

# ---------- CORE ----------
def process_symbol(symbol: str, cmc_vols: Dict[str,float]):
    # Klines cache
    k15 = fetch_klines_cached(symbol,"15m",200,TTL_15M); jitter_sleep(0.05,0.2)
    k30 = fetch_klines_cached(symbol,"30m",200,TTL_30M)

    closes15=[float(k[4]) for k in k15]
    highs15=[float(k[2]) for k in k15]
    lows15 =[float(k[3]) for k in k15]
    vols15 =[float(k[5]) for k in k15]
    closes30=[float(k[4]) for k in k30]

    res, sup = compute_levels(highs15,lows15,48)
    tr15, tr30 = trend_from_ema(closes15), trend_from_ema(closes30)
    rsi15 = rsi(closes15,14)

    jitter_sleep(0.05,0.2)
    price = fetch_price(symbol)
    sp_pct, sp_lbl = volume_spike_15m(vols15,20)
    base = symbol.replace("USDT","").replace("USD","")
    vol24h = cmc_vols.get(base)

    now_side = side_vs_band(price, sup, res)
    prev_side = STATE.last_side.get(symbol,"between")
    STATE.last_side[symbol] = now_side

    # Heartbeat
    if SEND_HEARTBEAT:
        now_min=int(time.time()//60)
        if now_min%INTERVAL_MIN==0 and STATE.last_hb_minute!=now_min:
            STATE.last_hb_minute=now_min
            send_telegram(build_heartbeat(symbol, price, tr15, tr30, res, sup, sp_lbl))

    # Setup (piano) su cambio banda
    if prev_side != now_side:
        send_telegram(build_setup(symbol, price, tr15, tr30, res, sup, sp_pct, sp_lbl, vol24h))

    # --- ENTRATE/USCITE ---
    if symbol not in STATE.pos: STATE.pos[symbol]=Position()
    P = STATE.pos[symbol]
    eL,sL,t1L,t2L = op_plan_long(res,sup)
    eS,sS,t1S,t2S = op_plan_short(res,sup)

    # Exit gestione posizione aperta
    if P.side == "long":
        if price <= P.sl:
            send_telegram(build_exit(symbol,"STOP (long)", price)); P.__init__()  # reset
        elif not P.hit_tp1 and price >= P.tp1:
            P.hit_tp1=True; send_telegram(build_exit(symbol,"TP1 (long)", price))
        elif price >= P.tp2:
            send_telegram(build_exit(symbol,"TP2 (long)", price)); P.__init__()
    elif P.side == "short":
        if price >= P.sl:
            send_telegram(build_exit(symbol,"STOP (short)", price)); P.__init__()
        elif not P.hit_tp1 and price <= P.tp1:
            P.hit_tp1=True; send_telegram(build_exit(symbol,"TP1 (short)", price))
        elif price <= P.tp2:
            send_telegram(build_exit(symbol,"TP2 (short)", price)); P.__init__()

    # Condizioni di ingresso (conferme)
    can_long  = price > eL and tr15=="rialzo" and tr30 in ("rialzo","neutro")
    can_short = price < eS and tr15=="ribasso" and tr30 in ("ribasso","neutro")
    if RSI_CONFIRMATION:
        if rsi15 is not None:
            can_long  = can_long  and rsi15 >= RSI_LONG_MIN
            can_short = can_short and rsi15 <= RSI_SHORT_MAX

    now_ts = time.time()
    # throttle: non ripetere entry alert più di 10 min
    THR = 600

    if P.side is None:
        if can_long and now_ts - P.last_entry_ts > THR:
            P.side="long"; P.entry=eL; P.sl=sL; P.tp1=t1L; P.tp2=t2L; P.hit_tp1=False; P.last_entry_ts=now_ts
            send_telegram(build_entry(symbol,"long",eL,sL,t1L,t2L,price,rsi15))
            # chart on entry
            try:
                img=make_chart_png(symbol,k15,res,sup,price); send_photo(img, caption=f"{symbol} — LONG setup")
            except Exception: pass
        elif can_short and now_ts - P.last_entry_ts > THR:
            P.side="short"; P.entry=eS; P.sl=sS; P.tp1=t1S; P.tp2=t2S; P.hit_tp1=False; P.last_entry_ts=now_ts
            send_telegram(build_entry(symbol,"short",eS,sS,t1S,t2S,price,rsi15))
            try:
                img=make_chart_png(symbol,k15,res,sup,price); send_photo(img, caption=f"{symbol} — SHORT setup")
            except Exception: pass

    # Grafico su condizioni forti (oltre a entry)
    want_chart=False
    if CHART_ON_BREAKOUT and prev_side!=now_side: want_chart=True
    if CHART_ON_SPIKE and sp_lbl=="↑ forte": want_chart=True
    if want_chart:
        last=STATE.last_chart_ts.get(symbol,0.0)
        if time.time()-last>=CHART_COOLDOWN_MIN*60:
            try:
                img=make_chart_png(symbol,k15,res,sup,price)
                send_photo(img, caption=f"{symbol} | R:{round_k(res)} S:{round_k(sup)}")
                STATE.last_chart_ts[symbol]=time.time()
            except Exception: pass

def main_loop():
    try: send_telegram("🟢 Bot avviato: monitor BTC & ETH (15m/30m).")
    except Exception: pass
    while True:
        try:
            cmc_vols = fetch_cmc_volumes_cached(SYMBOLS)
            for s in SYMBOLS: process_symbol(s, cmc_vols)
        except requests.HTTPError as e:
            code=getattr(e.response,"status_code",None)
            if code in (429,451):
                now=time.time()
                if now-LAST_RATE_WARN["ts"]>600:
                    try: send_telegram(f"⚠️ Rate limit {code}: rallento e riprovo…")
                    except Exception: pass
                    LAST_RATE_WARN["ts"]=now
            else:
                try: send_telegram(f"⚠️ Errore dati: HTTP {code or ''}".strip())
                except Exception: pass
        except Exception:
            pass
        time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main_loop()
