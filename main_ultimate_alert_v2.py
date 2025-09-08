#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BOT FAMIGLIA — TOP ULTRA (completo e corretto)
Watch-friendly · ATR · RSI · MACD · Volumetrica · Piano Operativo · Entrate/Uscite · Trailing SL
Anti-429 · CMC headers fix · Grafici con cooldown · Alert sonori

ENV OBBLIGATORIE:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID            # -100... (anche più ID separati da virgola)
  CMC_API_KEY

ENV CONSIGLIATE:
  SYMBOLS=BTCUSDT,ETHUSDT
  LOOP_SECONDS=240
  SEND_HEARTBEAT=false
  INTERVAL_MINUTES=15
  CHART_ON_BREAKOUT=true
  CHART_ON_SPIKE=true
  CHART_COOLDOWN_MIN=30
  DEFAULT_LEVERAGE=3

CONFIRM / RISK (default già buoni):
  RSI_CONFIRMATION=true
  RSI_LONG_MIN=55
  RSI_SHORT_MAX=45
  MACD_CONFIRMATION=true
  MACD_FAST=12
  MACD_SLOW=26
  MACD_SIGNAL=9
  USE_ATR_PLAN=true
  ATR_PERIOD=14
  ATR_MULT_SL=1.5       # stop = 1.5 * ATR
  ATR_MULT_TP1=1.0      # TP1  = 1.0 * ATR
  ATR_MULT_TP2=2.0      # TP2  = 2.0 * ATR
  ATR_MAX_LEV_PC=1.8    # se ATR% > 1.8% riduco leva suggerita
  MIN_ENTRY_COOLDOWN_MIN=10
  CAPITAL_USD=0
  RISK_PER_TRADE_PCT=0
"""

import os, io, time, random
from typing import List, Tuple, Dict, Optional
import requests

# -------------------- ENV --------------------
def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, str(default)).strip().lower()
    return v in ("1", "true", "yes", "y", "on")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
CMC_API_KEY        = os.environ.get("CMC_API_KEY", "")

SYMBOLS         = [s.strip().upper() for s in os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
LOOP_SECONDS    = int(os.environ.get("LOOP_SECONDS", "240"))
SEND_HEARTBEAT  = _env_bool("SEND_HEARTBEAT", False)
INTERVAL_MIN    = int(os.environ.get("INTERVAL_MINUTES", "15"))

CHART_ON_BREAKOUT   = _env_bool("CHART_ON_BREAKOUT", True)
CHART_ON_SPIKE      = _env_bool("CHART_ON_SPIKE", True)
CHART_COOLDOWN_MIN  = int(os.environ.get("CHART_COOLDOWN_MIN", "30"))

DEFAULT_LEVERAGE    = float(os.environ.get("DEFAULT_LEVERAGE", "3"))
CAPITAL_USD         = float(os.environ.get("CAPITAL_USD", "0"))
RISK_PER_TRADE_PCT  = float(os.environ.get("RISK_PER_TRADE_PCT", "0"))

RSI_CONFIRMATION    = _env_bool("RSI_CONFIRMATION", True)
RSI_LONG_MIN        = float(os.environ.get("RSI_LONG_MIN", "55"))
RSI_SHORT_MAX       = float(os.environ.get("RSI_SHORT_MAX", "45"))
MACD_CONFIRMATION   = _env_bool("MACD_CONFIRMATION", True)
MACD_FAST           = int(os.environ.get("MACD_FAST", "12"))
MACD_SLOW           = int(os.environ.get("MACD_SLOW", "26"))
MACD_SIGNAL         = int(os.environ.get("MACD_SIGNAL", "9"))

USE_ATR_PLAN        = _env_bool("USE_ATR_PLAN", True)
ATR_PERIOD          = int(os.environ.get("ATR_PERIOD", "14"))
ATR_MULT_SL         = float(os.environ.get("ATR_MULT_SL", "1.5"))
ATR_MULT_TP1        = float(os.environ.get("ATR_MULT_TP1", "1.0"))
ATR_MULT_TP2        = float(os.environ.get("ATR_MULT_TP2", "2.0"))
ATR_MAX_LEV_PC      = float(os.environ.get("ATR_MAX_LEV_PC", "1.8"))
MIN_ENTRY_COOLDOWN  = int(os.environ.get("MIN_ENTRY_COOLDOWN_MIN", "10")) * 60

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nelle Environment Variables.")

# -------------------- ENDPOINTS --------------------
MEXC_BASES = ["https://api.mexc.com", "https://www.mexc.com"]
BINANCE_BASES = [
    "https://api.binance.com","https://api1.binance.com","https://api2.binance.com",
    "https://api3.binance.com","https://api-gcp.binance.com","https://data-api.binance.vision"
]

# -------------------- CACHE / RATE-LIMIT --------------------
CACHE: Dict[str, dict] = {}
TTL_15M = 300
TTL_30M = 900
TTL_CMC = 900
LAST_RATE_WARN = {"ts": 0}

def _jitter(a=0.3, b=0.9): time.sleep(random.uniform(a, b))

def http_get(url: str, params: dict, timeout=15, retries=3, backoff=2.0, headers=None):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep((i+1) * backoff); continue
            r.raise_for_status()
            return r
        except Exception as e:
            last = e; time.sleep((i+1)*0.5)
    if last: raise last

def _json_with_fallback(paths: List[tuple], params: dict, timeout=15):
    last_err = None
    for base, path in paths:
        try:
            _jitter(0.15, 0.5)
            r = http_get(f"{base}{path}", params=params, timeout=timeout)
            return r.json()
        except Exception as e:
            last_err = e
    raise last_err

# -------------------- FETCH --------------------
def fetch_price(symbol: str) -> float:
    paths = [(b,"/api/v3/ticker/price") for b in MEXC_BASES] + [(b,"/api/v3/ticker/price") for b in BINANCE_BASES]
    data = _json_with_fallback(paths, {"symbol": symbol}, timeout=8)
    return float(data["price"])

def fetch_klines_cached(symbol: str, interval: str, limit: int, ttl: int) -> list:
    key = f"{symbol}_{interval}"; now = time.time()
    c = CACHE.get(key)
    if c and now - c["ts"] < ttl: return c["data"]
    paths = [(b,"/api/v3/klines") for b in MEXC_BASES] + [(b,"/api/v3/klines") for b in BINANCE_BASES]
    data = _json_with_fallback(paths, {"symbol": symbol,"interval": interval,"limit": limit}, timeout=12)
    CACHE[key] = {"ts": now, "data": data}; return data

def fetch_cmc_volumes_cached(symbols: List[str]) -> Dict[str, float]:
    now = time.time(); c = CACHE.get("CMC_VOL")
    if c and now - c["ts"] < TTL_CMC: return c["data"]
    if not CMC_API_KEY: return {}
    try:
        bases = sorted({s.replace("USDT","").replace("USD","") for s in symbols})
        url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
        headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
        _jitter(0.2,0.6)
        r = http_get(url, {"symbol": ",".join(bases), "convert":"USD"}, timeout=12, headers=headers)
        data = r.json().get("data", {}); out: Dict[str,float] = {}
        for base in bases:
            try: out[base] = float(data[base][0]["quote"]["USD"]["volume_24h"])
            except Exception: pass
        CACHE["CMC_VOL"] = {"ts": now, "data": out}; return out
    except Exception:
        return c["data"] if c else {}

# -------------------- INDICATORS --------------------
def ema(vals: List[float], length: int) -> List[float]:
    if not vals or length<=0 or len(vals)<length: return []
    k = 2/(length+1); out=[sum(vals[:length])/length]
    for v in vals[length:]: out.append(v*k + out[-1]*(1-k))
    return [None]*(len(vals)-len(out)) + out

def trend_from_ema(closes: List[float], fast=15, slow=50) -> str:
    efast, eslow = ema(closes, fast), ema(closes, slow)
    if not efast or not eslow or efast[-1] is None or eslow[-1] is None: return "n/d"
    return "rialzo" if efast[-1] > eslow[-1] else ("ribasso" if efast[-1] < eslow[-1] else "neutro")

def rsi(values: List[float], period: int=14) -> Optional[float]:
    if len(values) < period+1: return None
    gains=losses=0.0
    for i in range(-period,0):
        d=values[i]-values[i-1]
        if d>=0: gains+=d
        else: losses-=d
    if losses==0: return 100.0
    rs=(gains/period)/(losses/period)
    return 100 - 100/(1+rs)

def macd(values: List[float], fast=12, slow=26, signal=9) -> Tuple[Optional[float], Optional[float]]:
    if len(values) < slow + signal: return None, None
    ema_fast = ema(values, fast); ema_slow = ema(values, slow)
    macd_line=[]
    for i in range(len(values)):
        if ema_fast[i] is None or ema_slow[i] is None: macd_line.append(None)
        else: macd_line.append(ema_fast[i]-ema_slow[i])
    valid=[m for m in macd_line if m is not None]
    if len(valid) < signal: return None, None
    k=2/(signal+1); sig=[sum(valid[:signal])/signal]
    for v in valid[signal:]: sig.append(v*k + sig[-1]*(1-k))
    return valid[-1], sig[-1]

def true_range(h,l,prev_close): return max(h-l, abs(h-prev_close), abs(l-prev_close))

def atr_from_klines(klines: list, period: int=14) -> Optional[float]:
    if len(klines) < period+1: return None
    trs=[]; prev_close=float(klines[-period-1][4])
    for k in klines[-period:]:
        h=float(k[2]); l=float(k[3])
        trs.append(true_range(h,l,prev_close))
        prev_close=float(k[4])
    return sum(trs)/period if trs else None

# -------------------- FORMAT --------------------
def round_k(x: float)->str:
    step=100 if x>=10000 else 50; y=round(x/step)*step
    if y>=1000: return f"{int(y/1000)}k" if y%1000==0 else f"{y/1000:.1f}k"
    return f"{int(y)}"

def fmt_price(p: float)->str: return f"{p:,.0f}$".replace(",", ".")
def fmt_billions(x: float)->str:
    try: return f"{x/1e9:.1f}B"
    except Exception: return "n/d"

# -------------------- OPERATIVE PLAN --------------------
def op_plan_long(res: float, sup: float, atr: Optional[float], price: float)->Tuple[float,float,float,float]:
    entry=res
    if USE_ATR_PLAN and atr:
        sl  = entry - ATR_MULT_SL*atr
        tp1 = entry + ATR_MULT_TP1*atr
        tp2 = entry + ATR_MULT_TP2*atr
    else:
        sl  = sup*0.998; R=max(entry-sl,1e-6); tp1=entry+R; tp2=entry+2*R
    return entry, sl, tp1, tp2

def op_plan_short(res: float, sup: float, atr: Optional[float], price: float)->Tuple[float,float,float,float]:
    entry=sup
    if USE_ATR_PLAN and atr:
        sl  = entry + ATR_MULT_SL*atr
        tp1 = entry - ATR_MULT_TP1*atr
        tp2 = entry - ATR_MULT_TP2*atr
    else:
        sl  = res*1.002; R=max(sl-entry,1e-6); tp1=entry-R; tp2=entry-2*R
    return entry, sl, tp1, tp2

def suggested_leverage(atr: Optional[float], price: float)->int:
    base=int(DEFAULT_LEVERAGE)
    if not atr or price<=0: return base
    atr_pct=(atr/price)*100.0
    if atr_pct>ATR_MAX_LEV_PC: return max(1, base-1)
    return base

def sizing_line(entry: float, stop: float)->str:
    if CAPITAL_USD>0 and RISK_PER_TRADE_PCT>0:
        risk=CAPITAL_USD*(RISK_PER_TRADE_PCT/100.0)
        per_unit=abs(entry-stop)
        if per_unit<=0: return ""
        qty=risk/per_unit
        return f"💼 Rischio {RISK_PER_TRADE_PCT:.1f}% (~${risk:.0f}) | Size≈ {qty:.4f}"
    return ""

# -------------------- MESSAGES --------------------
def msg_setup(symbol, price, tr15, tr30, res, sup, sp_pct, sp_lbl, vol24h, lev):
    v24 = fmt_billions(vol24h) if vol24h is not None else "n/d"
    return (f"📉 {symbol}\n"
            f"💵 {fmt_price(price)}\n"
            f"📈 15m:{tr15} | 30m:{tr30}\n"
            f"🔑 R:{round_k(res)} | S:{round_k(sup)}\n"
            f"🔊 Vol15m: {sp_lbl} ({sp_pct:.0f}%) | 24h:{v24}\n"
            f"⚡ Leva suggerita: x{lev}")

def msg_entry(symbol, side, entry, sl, tp1, tp2, price, rsi_v, macd_ok, lev):
    side_name="LONG" if side=="long" else "SHORT"
    rsi_txt = f" | RSI:{rsi_v:.0f}" if rsi_v is not None else ""
    macd_txt= " | MACD✓" if macd_ok else ""
    return (f"🚨 ALERT TRADE [{symbol}] {side_name}\n"
            f"💵 {fmt_price(price)} | trigger {fmt_price(entry)}\n"
            f"🛡️ SL {fmt_price(sl)}  🎯 {fmt_price(tp1)} / {fmt_price(tp2)}  ⚡x{lev}{rsi_txt}{macd_txt}")

def msg_exit(symbol, reason, price): return f"🏁 EXIT TRADE [{symbol}] — {reason} a {fmt_price(price)}"
def msg_heartbeat(symbol, price, tr15, tr30, res, sup, sp_lbl):
    return f"🫀 {symbol}  {fmt_price(price)}  | 15m:{tr15}/30m:{tr30}  R:{round_k(res)} S:{round_k(sup)}  🔊{sp_lbl}"

# -------------------- TELEGRAM --------------------
def chat_ids()->List[str]: return [cid.strip() for cid in TELEGRAM_CHAT_ID.strip().split(",") if cid.strip()]

def tg_send(text: str):
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for cid in chat_ids():
        try: requests.post(url, data={"chat_id": cid, "text": text}, timeout=15).raise_for_status()
        except Exception: pass

# --- sendPhoto / chart ---
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def tg_photo(img_bytes: bytes, caption: str=""):
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    for cid in chat_ids():
        try:
            files={"photo":("chart.png", img_bytes)}
            data={"chat_id": cid, "caption": caption}
            requests.post(url, data=data, files=files, timeout=30).raise_for_status()
        except Exception: pass

def make_chart_png(symbol, k15, res, sup, price) -> bytes:
    # ✅ versione corretta (niente parentesi sbagliate)
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

# -------------------- STATE --------------------
class Position:
    def __init__(self):
        self.side: Optional[str] = None
        self.entry=self.sl=self.tp1=self.tp2=0.0
        self.hit_tp1=False
        self.last_entry_ts=0.0

class State:
    def __init__(self):
        self.last_side: Dict[str,str] = {}
        self.last_hb_minute=-1
        self.init_sent: Dict[str,bool] = {}
        self.last_chart_ts: Dict[str,float] = {}
        self.pos: Dict[str,Position] = {}

STATE = State()

def side_vs_band(p,sup,res)->str:
    if p>res: return "above"
    if p<sup: return "below"
    return "between"

# -------------------- CORE --------------------
def process_symbol(symbol: str, cmc_vols: Dict[str,float]):
    k15 = fetch_klines_cached(symbol,"15m",200,TTL_15M); _jitter(0.05,0.2)
    k30 = fetch_klines_cached(symbol,"30m",200,TTL_30M)

    closes15=[float(k[4]) for k in k15]
    highs15=[float(k[2]) for k in k15]
    lows15 =[float(k[3]) for k in k15]
    vols15 =[float(k[5]) for k in k15]
    closes30=[float(k[4]) for k in k30]

    res, sup = compute_levels(highs15, lows15, 48)
    tr15, tr30 = trend_from_ema(closes15), trend_from_ema(closes30)
    rsi15 = rsi(closes15,14)
    macd_line, macd_sig = macd(closes15, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    macd_ok_long  = (macd_line is not None and macd_sig is not None and macd_line > macd_sig)
    macd_ok_short = (macd_line is not None and macd_sig is not None and macd_line < macd_sig)

    _jitter(0.05,0.2)
    price = fetch_price(symbol)

    sp_pct, sp_lbl = volume_spike_15m(vols15,20)
    base = symbol.replace("USDT","").replace("USD","")
    vol24h = cmc_vols.get(base)

    atr = atr_from_klines(k15, ATR_PERIOD)
    lev = suggested_leverage(atr, price)

    now_side = side_vs_band(price, sup, res)
    prev_side = STATE.last_side.get(symbol,"between")
    STATE.last_side[symbol] = now_side

    # heartbeat
    if SEND_HEARTBEAT:
        now_min=int(time.time()//60)
        if now_min%INTERVAL_MIN==0 and STATE.last_hb_minute!=now_min:
            STATE.last_hb_minute=now_min
            tg_send(msg_heartbeat(symbol, price, tr15, tr30, res, sup, sp_lbl))

    # setup su cambio banda
    if prev_side != now_side:
        tg_send(msg_setup(symbol, price, tr15, tr30, res, sup, sp_pct, sp_lbl, vol24h, lev))

    # stato posizione
    if symbol not in STATE.pos: STATE.pos[symbol]=Position()
    P = STATE.pos[symbol]
    eL,sL,t1L,t2L = op_plan_long(res,sup,atr,price)
    eS,sS,t1S,t2S = op_plan_short(res,sup,atr,price)

    # uscite + trailing SL a BE dopo TP1
    if P.side == "long":
        if price <= P.sl:
            tg_send(msg_exit(symbol,"STOP (long)", price)); STATE.pos[symbol]=Position()
        elif not P.hit_tp1 and price >= P.tp1:
            P.hit_tp1=True; P.sl=max(P.sl, P.entry)
            tg_send(msg_exit(symbol,"TP1 (long) — SL→BE", price))
        elif price >= P.tp2:
            tg_send(msg_exit(symbol,"TP2 (long)", price)); STATE.pos[symbol]=Position()
    elif P.side == "short":
        if price >= P.sl:
            tg_send(msg_exit(symbol,"STOP (short)", price)); STATE.pos[symbol]=Position()
        elif not P.hit_tp1 and price <= P.tp1:
            P.hit_tp1=True; P.sl=min(P.sl, P.entry)
            tg_send(msg_exit(symbol,"TP1 (short) — SL→BE", price))
        elif price <= P.tp2:
            tg_send(msg_exit(symbol,"TP2 (short)", price)); STATE.pos[symbol]=Position()

    # condizioni di ingresso (RSI/MACD opzionali)
    can_long  = price > eL and tr15=="rialzo" and tr30 in ("rialzo","neutro")
    can_short = price < eS and tr15=="ribasso" and tr30 in ("ribasso","neutro")
    if RSI_CONFIRMATION and rsi15 is not None:
        can_long  = can_long  and rsi15 >= RSI_LONG_MIN
        can_short = can_short and rsi15 <= RSI_SHORT_MAX
    if MACD_CONFIRMATION:
        can_long  = can_long  and macd_ok_long
        can_short = can_short and macd_ok_short

    now_ts=time.time()
    if P.side is None:
        if can_long and now_ts - P.last_entry_ts > MIN_ENTRY_COOLDOWN:
            P.side="long"; P.entry=eL; P.sl=sL; P.tp1=t1L; P.tp2=t2L; P.hit_tp1=False; P.last_entry_ts=now_ts
            tg_send(msg_entry(symbol,"long",eL,sL,t1L,t2L,price,rsi15, macd_ok_long, lev))
            try:
                img=make_chart_png(symbol,k15,res,sup,price); tg_photo(img, caption=f"{symbol} — LONG setup")
            except Exception: pass
        elif can_short and now_ts - P.last_entry_ts > MIN_ENTRY_COOLDOWN:
            P.side="short"; P.entry=eS; P.sl=sS; P.tp1=t1S; P.tp2=t2S; P.hit_tp1=False; P.last_entry_ts=now_ts
            tg_send(msg_entry(symbol,"short",eS,sS,t1S,t2S,price,rsi15, macd_ok_short, lev))
            try:
                img=make_chart_png(symbol,k15,res,sup,price); tg_photo(img, caption=f"{symbol} — SHORT setup")
            except Exception: pass

    # grafico su segnali forti/cambio banda
    want_chart=False
    if CHART_ON_BREAKOUT and prev_side!=now_side: want_chart=True
    if CHART_ON_SPIKE and sp_lbl=="↑ forte":      want_chart=True
    if want_chart:
        last=STATE.last_chart_ts.get(symbol,0.0)
        if time.time()-last >= CHART_COOLDOWN_MIN*60:
            try:
                img=make_chart_png(symbol,k15,res,sup,price)
                tg_photo(img, caption=f"{symbol} | R:{round_k(res)} S:{round_k(sup)}")
                STATE.last_chart_ts[symbol]=time.time()
            except Exception: pass

def main_loop():
    try: tg_send("🟢 Bot avviato: monitor BTC & ETH (15m/30m).")
    except Exception: pass
    while True:
        try:
            cmc_vols = fetch_cmc_volumes_cached(SYMBOLS)
            for s in SYMBOLS:
                process_symbol(s, cmc_vols)
        except requests.HTTPError as e:
            code=getattr(e.response,"status_code",None)
            if code in (429,451):
                now=time.time()
                if now-LAST_RATE_WARN["ts"]>600:
                    try: tg_send(f"⚠️ Rate limit {code}: rallento e riprovo…")
                    except Exception: pass
                    LAST_RATE_WARN["ts"]=now
            else:
                try: tg_send(f"⚠️ Errore dati: HTTP {code or ''}".strip())
                except Exception: pass
        except Exception:
            pass
        time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main_loop()
