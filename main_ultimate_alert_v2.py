#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BotFamiglia – TOP SAFE (Render)
- Solo BTCUSDT (di default), timeframe 15m/30m
- Trend EMA(20/50) + RSI(14) con soglie conservative 60/40
- Piani SL/TP su ATR (SL 1.8x; TP1 1.2x; TP2 2.0x) e trailing morbido 0.8x
- Momentum DISATTIVATO per evitare ingressi aggressivi
- Chart su breakout/volume spike con cooldown
"""

import os, io, time, random, requests
from typing import Dict, List, Optional

# ============== ENV ==============
def _b(x, d=False): return os.getenv(x, str(d)).strip().lower() in ("1","true","y","yes","on")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","")
CHAT  = os.getenv("TELEGRAM_CHAT_ID","")
CMC_KEY = os.getenv("CMC_API_KEY","")

SYMBOLS      = [s.strip().upper() for s in os.getenv("SYMBOLS","BTCUSDT").split(",") if s.strip()]
INTERVAL_MIN = int(os.getenv("INTERVAL_MINUTES","15"))
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS","240"))

# Conferme (conservative)
RSI_CONFIRMATION = _b("RSI_CONFIRMATION", True)
RSI_LONG_MIN     = float(os.getenv("RSI_LONG_MIN","60"))
RSI_SHORT_MAX    = float(os.getenv("RSI_SHORT_MAX","40"))
MACD_CONFIRMATION = _b("MACD_CONFIRMATION", True)
MACD_FAST   = int(os.getenv("MACD_FAST","12"))
MACD_SLOW   = int(os.getenv("MACD_SLOW","26"))
MACD_SIGNAL = int(os.getenv("MACD_SIGNAL","9"))

# ATR & piani
USE_ATR_PLAN   = _b("USE_ATR_PLAN", True)
ATR_PERIOD     = int(os.getenv("ATR_PERIOD","14"))
ATR_MULT_SL    = float(os.getenv("ATR_MULT_SL","1.8"))
ATR_MULT_TP1   = float(os.getenv("ATR_MULT_TP1","1.2"))
ATR_MULT_TP2   = float(os.getenv("ATR_MULT_TP2","2.0"))
TRAIL_ATR_MULT = float(os.getenv("TRAIL_ATR_MULT","0.8"))
BE_OFFSET_ATR_MULT = float(os.getenv("BE_OFFSET_ATR_MULT","0.2"))

# Momentum OFF (di default)
MOMENTUM_TRIGGER       = _b("MOMENTUM_TRIGGER", False)
MOMENTUM_LOOKBACK_BARS = int(os.getenv("MOMENTUM_LOOKBACK_BARS","4"))
MOMENTUM_PCT           = float(os.getenv("MOMENTUM_PCT","1.2"))

# extra
SEND_HEARTBEAT   = _b("SEND_HEARTBEAT", False)
DEFAULT_LEVERAGE = float(os.getenv("DEFAULT_LEVERAGE","3"))
ATR_MAX_LEV_PC   = float(os.getenv("ATR_MAX_LEV_PC","1.8"))

if not TOKEN or not CHAT:
    raise RuntimeError("Imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID in Render.")

# ============== HTTP/Providers ==============
MEXC = ["https://api.mexc.com","https://www.mexc.com"]
BIN  = ["https://api.binance.com","https://api1.binance.com","https://api2.binance.com",
        "https://api3.binance.com","https://api-gcp.binance.com","https://data-api.binance.vision"]
CACHE: Dict[str, dict] = {}
TTL_15M, TTL_30M, TTL_CMC = 300, 900, 900
LAST_RATE_WARN = {"ts":0}

def _jitter(a=0.25,b=0.7): time.sleep(random.uniform(a,b))
def _get(url, params, timeout=15, retries=3, backoff=2.0, headers=None):
    last=None
    for i in range(retries):
        try:
            r=requests.get(url, params=params, timeout=timeout, headers=headers)
            if r.status_code==429: time.sleep((i+1)*backoff); continue
            r.raise_for_status(); return r
        except Exception as e: last=e; time.sleep((i+1)*0.4)
    raise last

def _json_try(paths, params, timeout=12, headers=None):
    last=None
    for base, path in paths:
        try:
            _jitter(); r=_get(f"{base}{path}", params, timeout=timeout, headers=headers); return r.json()
        except Exception as e: last=e
    raise last

def fetch_price(sym)->float:
    paths=[(b,"/api/v3/ticker/price") for b in (MEXC+BIN)]
    return float(_json_try(paths, {"symbol":sym}, timeout=8)["price"])

def fetch_klines_cached(sym, interval, limit, ttl)->list:
    key=f"{sym}_{interval}"; now=time.time(); c=CACHE.get(key)
    if c and now-c["ts"]<ttl: return c["data"]
    paths=[(b,"/api/v3/klines") for b in (MEXC+BIN)]
    data=_json_try(paths, {"symbol":sym,"interval":interval,"limit":limit}, timeout=12)
    CACHE[key]={"ts":now,"data":data}; return data

def fetch_cmc_volumes_cached(symbols)->Dict[str,float]:
    now=time.time(); c=CACHE.get("CMC_VOL")
    if c and now-c["ts"]<TTL_CMC: return c["data"]
    if not CMC_KEY: return {}
    try:
        bases=sorted({s.replace("USDT","").replace("USD","") for s in symbols})
        url="https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
        headers={"X-CMC_PRO_API_KEY":CMC_KEY}
        r=_get(url, {"symbol":",".join(bases),"convert":"USD"}, headers=headers, timeout=12).json()
        out={}
        for b in bases:
            try: out[b]=float(r["data"][b][0]["quote"]["USD"]["volume_24h"])
            except Exception: pass
        CACHE["CMC_VOL"]={"ts":now,"data":out}; return out
    except Exception:
        return c["data"] if c else {}

# ============== Indicatori ==============
def ema(vals:List[float], n:int)->List[float]:
    if len(vals)<n: return []
    k=2/(n+1); out=[sum(vals[:n])/n]
    for v in vals[n:]: out.append(v*k + out[-1]*(1-k))
    return [None]*(len(vals)-len(out))+out

def rsi(vals, period=14)->Optional[float]:
    if len(vals)<period+1: return None
    g=l=0.0
    for i in range(-period,0):
        d=vals[i]-vals[i-1]
        g+=max(d,0); l+=max(-d,0)
    if l==0: return 100.0
    rs=(g/period)/(l/period)
    return 100-100/(1+rs)

def macd(values, fast=12, slow=26, signal=9):
    if len(values)<slow+signal: return None,None
    ef, es = ema(values, fast), ema(values, slow)
    line=[(ef[i]-es[i]) if (ef[i] is not None and es[i] is not None) else None for i in range(len(values))]
    valid=[m for m in line if m is not None]
    if len(valid)<signal: return None,None
    k=2/(signal+1); sig=[sum(valid[:signal])/signal]
    for v in valid[signal:]: sig.append(v*k + sig[-1]*(1-k))
    return valid[-1], sig[-1]

def true_range(h,l,pc): return max(h-l, abs(h-pc), abs(l-pc))
def atr_from_klines(kl, period=14)->Optional[float]:
    if len(kl)<period+1: return None
    trs=[]; pc=float(kl[-period-1][4])
    for k in kl[-period:]:
        trs.append(true_range(float(k[2]), float(k[3]), pc))
        pc=float(k[4])
    return sum(trs)/period if trs else None

# ============== TG helpers ==============
def chat_ids(): return [c.strip() for c in CHAT.split(",") if c.strip()]
def tg_send(text):
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for cid in chat_ids():
        try: requests.post(url, data={"chat_id":cid, "text":text}, timeout=15).raise_for_status()
        except Exception: pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
def tg_photo(img, caption=""):
    url=f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    for cid in chat_ids():
        try: requests.post(url, data={"chat_id":cid,"caption":caption},
                           files={"photo":("chart.png", img)}, timeout=30).raise_for_status()
        except Exception: pass

def make_chart_png(symbol, k15, res, sup, price)->bytes:
    closes=[float(k[4]) for k in k15][-100:]
    xs=list(range(len(closes)))
    plt.figure(figsize=(6,3), dpi=200)
    plt.plot(xs, closes)
    plt.axhline(res, linestyle="--"); plt.axhline(sup, linestyle="--")
    plt.title(f"{symbol}  |  {price:,.0f}$".replace(",",".")); plt.tight_layout()
    buf=io.BytesIO(); plt.savefig(buf, format="png"); plt.close(); buf.seek(0)
    return buf.read()

# ============== Util & Stato ==============
def round_k(x:float)->str:
    step=100 if x>=10000 else 50; y=round(x/step)*step
    return (f"{int(y/1000)}k" if y%1000==0 else f"{y/1000:.1f}k") if y>=1000 else f"{int(y)}"
def trend_from_ema(closes, fast=20, slow=50)->str:
    ef, es = ema(closes, fast), ema(closes, slow)
    if not ef or not es or ef[-1] is None or es[-1] is None: return "n/d"
    return "rialzo" if ef[-1]>es[-1] else ("ribasso" if ef[-1]<es[-1] else "neutro")

class Position:
    def __init__(self):
        self.side=None; self.entry=self.sl=self.tp1=self.tp2=0.0
        self.hit_tp1=False; self.last_entry_ts=0.0; self.extreme=None

class State:
    def __init__(self):
        self.last_side={}; self.last_hb_minute=-1; self.last_chart_ts={}; self.pos={}
STATE=State()

def side_vs_band(p,sup,res):
    return "above" if p>res else ("below" if p<sup else "between")

def volume_spike(vols, lookback=20):
    if len(vols)<lookback+1: return 0.0,"n/d"
    avg=sum(vols[-lookback-1:-1])/lookback; last=vols[-1]
    if avg<=0: return 0.0,"n/d"
    pct=(last/avg-1)*100
    label="≈"
    if   pct>=100: label="↑ forte"
    elif pct>=25:  label="↑"
    elif pct<=-25: label="↓"
    return pct,label

# ============== Messaggi ==============
def fmt_price(p:float)->str: return f"{p:,.0f}$".replace(",",".")
def fmt_billions(x:float)->str:
    try: return f"{x/1e9:.1f}B"
    except: return "n/d"

def msg_setup(sym, price, tr15, tr30, res, sup, sp_lbl, sp_pct, v24, lev):
    vv = fmt_billions(v24) if v24 is not None else "n/d"
    return (f"📉 {sym}\n💵 {fmt_price(price)}\n"
            f"📈 15m:{tr15} | 30m:{tr30}\n"
            f"🔑 R:{round_k(res)} | S:{round_k(sup)}\n"
            f"🔊 Vol15m: {sp_lbl} ({sp_pct:.0f}%) | 24h:{vv}\n"
            f"⚡ Leva: x{lev}")

def msg_entry(sym, side, entry, sl, tp1, tp2, price, rsi_v, macd_ok, lev):
    side_n="LONG" if side=="long" else "SHORT"
    r = f" | RSI:{rsi_v:.0f}" if rsi_v is not None else ""
    m = " | MACD✓" if macd_ok else ""
    return (f"🚨 TRADE [{sym}] {side_n}\n"
            f"💵 {fmt_price(price)} | trigger {fmt_price(entry)}\n"
            f"🛡️ SL {fmt_price(sl)}  🎯 {fmt_price(tp1)} / {fmt_price(tp2)}  ⚡x{lev}{r}{m}")

def msg_exit(sym, reason, price):
    return f"🏁 EXIT [{sym}] — {reason} a {fmt_price(price)}"

# ============== Piano operativo ==============
def op_plan_long(res, sup, atr, price):
    entry=res
    if USE_ATR_PLAN and atr:
        sl  = entry - ATR_MULT_SL*atr
        tp1 = entry + ATR_MULT_TP1*atr
        tp2 = entry + ATR_MULT_TP2*atr
    else:
        sl=sup*0.998; R=max(entry-sl,1e-6); tp1=entry+R; tp2=entry+2*R
    return entry, sl, tp1, tp2

def op_plan_short(res, sup, atr, price):
    entry=sup
    if USE_ATR_PLAN and atr:
        sl  = entry + ATR_MULT_SL*atr
        tp1 = entry - ATR_MULT_TP1*atr
        tp2 = entry - ATR_MULT_TP2*atr
    else:
        sl=res*1.002; R=max(sl-entry,1e-6); tp1=entry-R; tp2=entry-2*R
    return entry, sl, tp1, tp2

def suggested_leverage(atr, price):
    if not atr or price<=0: return int(DEFAULT_LEVERAGE)
    return max(1, int(DEFAULT_LEVERAGE) - (1 if (atr/price*100)>ATR_MAX_LEV_PC else 0))

# ============== Core ==============
def process_symbol(symbol, cmc_vols):
    k15=fetch_klines_cached(symbol,"15m",200,TTL_15M); _jitter()
    k30=fetch_klines_cached(symbol,"30m",200,TTL_30M)

    closes15=[float(k[4]) for k in k15]
    highs15=[float(k[2]) for k in k15]
    lows15 =[float(k[3]) for k in k15]
    vols15 =[float(k[5]) for k in k15]
    closes30=[float(k[4]) for k in k30]

    res, sup = max(highs15[-48:]), min(lows15[-48:])
    tr15, tr30 = trend_from_ema(closes15), trend_from_ema(closes30)
    rsi15 = rsi(closes15,14)
    macd_line, macd_sig = macd(closes15, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    macd_ok_long  = (macd_line is not None and macd_sig is not None and macd_line>macd_sig)
    macd_ok_short = (macd_line is not None and macd_sig is not None and macd_line<macd_sig)

    price=fetch_price(symbol)
    sp_pct, sp_lbl = volume_spike(vols15,20)
    base=symbol.replace("USDT","").replace("USD",""); vol24=cmc_vols.get(base)
    atr=atr_from_klines(k15, ATR_PERIOD); lev=suggested_leverage(atr, price)

    prev=STATE.last_side.get(symbol,"between")
    now_side = side_vs_band(price,sup,res)
    STATE.last_side[symbol]=now_side

    if prev!=now_side:
        tg_send(msg_setup(symbol,price,tr15,tr30,res,sup,sp_lbl,sp_pct,vol24,lev))

    if symbol not in STATE.pos: STATE.pos[symbol]=Position()
    P=STATE.pos[symbol]

    eL,sL,t1L,t2L = op_plan_long(res,sup,atr,price)
    eS,sS,t1S,t2S = op_plan_short(res,sup,atr,price)

    # gestione posizione (trailing morbido + TP1 -> BE±offset)
    if P.side=="long":
        if P.extreme is None or price>P.extreme: P.extreme=price
        if atr:
            trail = P.extreme - TRAIL_ATR_MULT*atr
            P.sl = max(P.sl, trail)
        if price<=P.sl:
            tg_send(msg_exit(symbol,"STOP (long)", price)); STATE.pos[symbol]=Position()
        elif not P.hit_tp1 and price>=P.tp1:
            P.hit_tp1=True; be_off = (BE_OFFSET_ATR_MULT*atr if atr else 0.0)
            P.sl = max(P.sl, P.entry + be_off)
            tg_send(msg_exit(symbol, f"TP1 50% (long) — SL→BE", price))
        elif price>=P.tp2:
            tg_send(msg_exit(symbol,"TP2 (long)", price)); STATE.pos[symbol]=Position()

    elif P.side=="short":
        if P.extreme is None or price<P.extreme: P.extreme=price
        if atr:
            trail = P.extreme + TRAIL_ATR_MULT*atr
            P.sl = min(P.sl, trail)
        if price>=P.sl:
            tg_send(msg_exit(symbol,"STOP (short)", price)); STATE.pos[symbol]=Position()
        elif not P.hit_tp1 and price<=P.tp1:
            P.hit_tp1=True; be_off = (BE_OFFSET_ATR_MULT*atr if atr else 0.0)
            P.sl = min(P.sl, P.entry - be_off)
            tg_send(msg_exit(symbol, f"TP1 50% (short) — SL→BE", price))
        elif price<=P.tp2:
            tg_send(msg_exit(symbol,"TP2 (short)", price)); STATE.pos[symbol]=Position()

    # ingressi (conferme conservative)
    can_long  = (price>eL and tr15=="rialzo"  and tr30 in ("rialzo","neutro"))
    can_short = (price<eS and tr15=="ribasso" and tr30 in ("ribasso","neutro"))
    if RSI_CONFIRMATION and rsi15 is not None:
        can_long  = can_long  and rsi15>=RSI_LONG_MIN
        can_short = can_short and rsi15<=RSI_SHORT_MAX
    if MACD_CONFIRMATION:
        can_long  = can_long  and macd_ok_long
        can_short = can_short and macd_ok_short

    # momentum disattivato di default (lasciato per futura prova)
    if MOMENTUM_TRIGGER and len(closes15)>MOMENTUM_LOOKBACK_BARS:
        ref=closes15[-MOMENTUM_LOOKBACK_BARS]
        if ref>0:
            mom=(price/ref-1)*100
            if mom>=MOMENTUM_PCT and tr15=="rialzo": can_long=True
            if mom<=-MOMENTUM_PCT and tr15=="ribasso": can_short=True

    now=time.time()
    if P.side is None:
        if can_long and now-P.last_entry_ts>INTERVAL_MIN*60:
            P.side="long"; P.entry=eL; P.sl=sL; P.tp1=t1L; P.tp2=t2L; P.hit_tp1=False; P.last_entry_ts=now; P.extreme=None
            tg_send(msg_entry(symbol,"long",eL,sL,t1L,t2L,price,rsi15,macd_ok_long,lev))
            try: tg_photo(make_chart_png(symbol,k15,res,sup,price), f"{symbol} — LONG setup")
            except Exception: pass
        elif can_short and now-P.last_entry_ts>INTERVAL_MIN*60:
            P.side="short"; P.entry=eS; P.sl=sS; P.tp1=t1S; P.tp2=t2S; P.hit_tp1=False; P.last_entry_ts=now; P.extreme=None
            tg_send(msg_entry(symbol,"short",eS,sS,t1S,t2S,price,rsi15,macd_ok_short,lev))
            try: tg_photo(make_chart_png(symbol,k15,res,sup,price), f"{symbol} — SHORT setup")
            except Exception: pass

def main_loop():
    tg_send("🟢 Bot SAFE avviato: BTCUSDT 15m/30m, ingressi selettivi.")
    while True:
        try:
            cmc=fetch_cmc_volumes_cached(SYMBOLS)
            for s in SYMBOLS: process_symbol(s, cmc)
        except requests.HTTPError as e:
            code=getattr(e.response,"status_code",None)
            if code in (429,451):
                if time.time()-LAST_RATE_WARN["ts"]>600:
                    tg_send(f"⚠️ Rate limit {code}: rallento e riprovo…")
                    LAST_RATE_WARN["ts"]=time.time()
            else:
                tg_send(f"⚠️ Errore dati: HTTP {code or ''}".strip())
        except Exception:
            pass
        time.sleep(LOOP_SECONDS)

if __name__=="__main__":
    main_loop()
