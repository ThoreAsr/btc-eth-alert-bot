#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zeta BOT (Render) — Analisi BTC/ETH 15m:
EMA(20/50) trend + MACD/RSI + Break strutturale + ROC + Spike volumi
Alert su Telegram con piani SL/TP su ATR e grafico.
"""

import os, io, time, random, math
from typing import Dict, List, Tuple, Optional
import requests

# ------------ ENV
def _b(name, d=False): return os.getenv(name, str(d)).strip().lower() in ("1","true","y","yes","on")
def _i(name, d): return int(os.getenv(name, str(d)))
def _f(name, d): return float(os.getenv(name, str(d)))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN",""); CHAT=os.getenv("TELEGRAM_CHAT_ID","")
CMC_KEY = os.getenv("CMC_API_KEY","")

SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS","BTCUSDT,ETHUSDT").split(",") if s.strip()]
INTERVAL_MIN = _i("INTERVAL_MINUTES",15)
LOOP_SECONDS = _i("LOOP_SECONDS",120)

RSI_CONFIRM = _b("RSI_CONFIRMATION", True)
RSI_LONG_MIN = _f("RSI_LONG_MIN", 55)
RSI_SHORT_MAX= _f("RSI_SHORT_MAX",45)

MACD_CONFIRM = _b("MACD_CONFIRMATION", True)
MACD_FAST    = _i("MACD_FAST",12)
MACD_SLOW    = _i("MACD_SLOW",26)
MACD_SIGNAL  = _i("MACD_SIGNAL",9)

ATR_PERIOD   = _i("ATR_PERIOD",14)
ATR_MULT_SL  = _f("ATR_MULT_SL",1.2)
ATR_MULT_TP1 = _f("ATR_MULT_TP1",1.0)
ATR_MULT_TP2 = _f("ATR_MULT_TP2",1.8)
BE_OFF_ATR   = _f("BE_OFFSET_ATR_MULT",0.2)

SWING_LKB    = _i("SWING_LOOKBACK",12)
BREAK_BUF_P  = _f("BREAK_BUFFER_PCT",0.02)
ROC_LKB      = _i("ROC_LOOKBACK_BARS",4)
ROC_MIN_PCT  = _f("ROC_MIN_PCT",0.25)

VOL_LKB      = _i("VOL_SPIKE_LKB",20)
VOL_MULT     = _f("VOL_SPIKE_MULT",1.5)

CHART_ON_BREAKOUT = _b("CHART_ON_BREAKOUT", True)
CHART_COOLDOWN_MIN= _i("CHART_COOLDOWN_MIN",30)

DEFAULT_LEV  = _i("DEFAULT_LEVERAGE",3)
SEND_HB      = _b("SEND_HEARTBEAT", False)

if not TOKEN or not CHAT:
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in env!")

# ------------ HTTP providers
MEXC = ["https://api.mexc.com","https://www.mexc.com"]
BIN  = ["https://api.binance.com","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com"]
CACHE: Dict[str,dict] = {}
TTL_15M=300; TTL_30M=900; TTL_CMC=900

def _j(): time.sleep(random.uniform(0.2,0.6))
def http_get(u, params=None, timeout=12, headers=None, retries=3):
    last=None
    for i in range(retries):
        try:
            r=requests.get(u, params=params, timeout=timeout, headers=headers)
            if r.status_code==429: time.sleep(0.5*(i+1)); continue
            r.raise_for_status(); return r
        except Exception as e:
            last=e; time.sleep(0.3*(i+1))
    raise last

def _fallback_json(paths:List[Tuple[str,str]], params=None, timeout=12, headers=None):
    last=None
    for base, path in paths:
        try:
            _j(); r=http_get(base+path, params=params, timeout=timeout, headers=headers)
            return r.json()
        except Exception as e: last=e
    raise last

def price(sym)->float:
    p=[(b,"/api/v3/ticker/price") for b in MEXC+BIN]
    return float(_fallback_json(p, {"symbol":sym})["price"])

def klines(sym, interval, limit)->list:
    key=f"K_{sym}_{interval}"
    now=time.time()
    c=CACHE.get(key)
    if c and now-c["ts"]<TTL_15M: return c["data"]
    p=[(b,"/api/v3/klines") for b in MEXC+BIN]
    data=_fallback_json(p, {"symbol":sym,"interval":interval,"limit":limit})
    CACHE[key]={"ts":now,"data":data}
    return data

def cmc_vol(symbols)->Dict[str,float]:
    if not CMC_KEY: return {}
    now=time.time()
    c=CACHE.get("CMC")
    if c and now-c["ts"]<TTL_CMC: return c["data"]
    bases=sorted({s.replace("USDT","").replace("USD","") for s in symbols})
    try:
        r=http_get("https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest",
                   {"symbol":",".join(bases),"convert":"USD"},
                   headers={"X-CMC_PRO_API_KEY":CMC_KEY}).json()
        out={}
        for b in bases:
            out[b]=float(r["data"][b][0]["quote"]["USD"]["volume_24h"])
        CACHE["CMC"]={"ts":now,"data":out}
        return out
    except Exception:
        return {}

# ------------ math/indicators
def ema(vals, n):
    if len(vals)<n: return []
    k=2/(n+1); out=[sum(vals[:n])/n]
    for v in vals[n:]: out.append(v*k + out[-1]*(1-k))
    return [None]*(len(vals)-len(out))+out

def rsi(vals, n=14):
    if len(vals)<n+1: return None
    g=l=0.0
    for i in range(-n,0):
        d=vals[i]-vals[i-1]
        g+=max(d,0); l+=max(-d,0)
    if l==0: return 100.0
    rs=(g/n)/(l/n); return 100-100/(1+rs)

def macd(values, f=12,s=26,sg=9):
    if len(values)<s+sg: return None,None
    ef, es = ema(values,f), ema(values,s)
    line=[(ef[i]-es[i]) if ef[i] is not None and es[i] is not None else None for i in range(len(values))]
    valid=[x for x in line if x is not None]
    if len(valid)<sg: return None,None
    k=2/(sg+1); sig=[sum(valid[:sg])/sg]
    for v in valid[sg:]: sig.append(v*k + sig[-1]*(1-k))
    return valid[-1], sig[-1]

def tr(h,l,pc): return max(h-l, abs(h-pc), abs(l-pc))
def atr(kl, n=14):
    if len(kl)<n+1: return None
    trs=[]; pc=float(kl[-n-1][4])
    for k in kl[-n:]:
        trs.append(tr(float(k[2]),float(k[3]),pc))
        pc=float(k[4])
    return sum(trs)/n

def highest(vals): return max(vals) if vals else None
def lowest(vals):  return min(vals) if vals else None

# ------------ telegram
def tg_send(txt):
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for cid in [c.strip() for c in CHAT.split(",") if c.strip()]:
        try: requests.post(url, data={"chat_id":cid,"text":txt}, timeout=15).raise_for_status()
        except Exception: pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
def tg_chart(sym, closes, res, sup, price):
    xs=list(range(len(closes)))
    plt.figure(figsize=(6,3), dpi=200)
    plt.plot(xs, closes)
    if res: plt.axhline(res, ls="--")
    if sup: plt.axhline(sup, ls="--")
    plt.title(f"{sym}  |  {price:,.0f}$".replace(",","."))
    plt.tight_layout()
    buff=io.BytesIO(); plt.savefig(buff, format="png"); plt.close(); buff.seek(0)
    url=f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    for cid in [c.strip() for c in CHAT.split(",") if c.strip()]:
        try: requests.post(url, data={"chat_id":cid}, files={"photo":("c.png",buff.read())}, timeout=30)
        except Exception: pass

# ------------ state
class P: pass
STATE = {
    "last_side":{},          # between/above/below
    "last_chart_ts":{},      # cooldown chart
    "pos":{s:P() for s in SYMBOLS}
}
for s in SYMBOLS:
    pp=STATE["pos"][s]; pp.side=None; pp.entry=pp.sl=pp.tp1=pp.tp2=0.0; pp.hit=False; pp.ext=None; pp.last_ts=0

# ------------ core
def process(sym, cmcdata):
    # dati
    k15 = klines(sym,"15m",  200)
    k30 = klines(sym,"30m",  200)
    closes15=[float(k[4]) for k in k15]
    highs15 =[float(k[2]) for k in k15]
    lows15  =[float(k[3]) for k in k15]
    vols15  =[float(k[5]) for k in k15]
    closes30=[float(k[4]) for k in k30]

    e20,e50 = ema(closes15,20), ema(closes15,50)
    up   = e20 and e50 and e20[-1] and e50[-1] and e20[-1]>e50[-1]
    down = e20 and e50 and e20[-1] and e50[-1] and e20[-1]<e50[-1]

    r = rsi(closes15,14)
    mL,mS = macd(closes15, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    macd_long  = (mL is not None and mS is not None and mL>mS)
    macd_short = (mL is not None and mS is not None and mL<mS)

    pr = price(sym)
    a  = atr(k15, ATR_PERIOD)

    # swing & break confermato
    hh = max(highs15[-(SWING_LKB+1):-1]); ll = min(lows15[-(SWING_LKB+1):-1])
    buf = pr*BREAK_BUF_P
    lastClose = closes15[-2]

    # rate of change
    roc = (closes15[-1]/closes15[-(ROC_LKB+1)] - 1)*100 if len(closes15)>ROC_LKB+1 else 0.0

    # volume spike 15m
    avg = sum(vols15[-(VOL_LKB+1):-1])/max(1,VOL_LKB)
    v_spike = vols15[-1] >= VOL_MULT*avg

    # side vs banda (per messaggi setup)
    side = "above" if pr>hh else ("below" if pr<ll else "between")
    prev = STATE["last_side"].get(sym,"between")
    STATE["last_side"][sym]=side

    base=sym.replace("USDT","").replace("USD","")
    v24 = cmcdata.get(base)

    # messaggi setup al cambio banda
    if prev!=side:
        tg_send(f"📊 {sym}  |  {pr:,.0f}$\n15m trend: {'UP' if up else ('DOWN' if down else 'FLAT')}\nR:{hh:,.0f}  S:{ll:,.0f}\nVol spike: {'YES' if v_spike else 'no'}  |  24h vol: {('%.1fB'%(v24/1e9)) if v24 else 'n/d'}".replace(",","."))
        if CHART_ON_BREAKOUT:
            last=STATE["last_chart_ts"].get(sym,0.0)
            if time.time()-last>=CHART_COOLDOWN_MIN*60:
                try: tg_chart(sym, closes15[-100:], hh, ll, pr); STATE["last_chart_ts"][sym]=time.time()
                except Exception: pass

    # stato posizione virtuale (solo alert)
    P=STATE["pos"][sym]

    # piani
    def plan_long():
        if not a: return None
        entry=hh+buf; sl=entry-ATR_MULT_SL*a; tp1=entry+ATR_MULT_TP1*a; tp2=entry+ATR_MULT_TP2*a
        return entry,sl,tp1,tp2
    def plan_short():
        if not a: return None
        entry=ll-buf; sl=entry+ATR_MULT_SL*a; tp1=entry-ATR_MULT_TP1*a; tp2=entry-ATR_MULT_TP2*a
        return entry,sl,tp1,tp2

    # gestioni virtuali
    if P.side=="long":
        if P.ext is None or pr>P.ext: P.ext=pr
        if pr<=P.sl: tg_send(f"🏁 {sym}: STOP long @ {pr:,.0f}$".replace(",", ".")); P.side=None
        elif not P.hit and pr>=P.tp1:
            P.hit=True; be=P.entry+BE_OFF_ATR*a; P.sl=max(P.sl,be)
            tg_send(f"✅ {sym}: TP1 long. SL→BE+off ({be:,.0f}$)".replace(",","."))

    elif P.side=="short":
        if P.ext is None or pr<P.ext: P.ext=pr
        if pr>=P.sl: tg_send(f"🏁 {sym}: STOP short @ {pr:,.0f}$".replace(",", ".")); P.side=None
        elif not P.hit and pr<=P.tp1:
            P.hit=True; be=P.entry-BE_OFF_ATR*a; P.sl=min(P.sl,be)
            tg_send(f"✅ {sym}: TP1 short. SL→BE+off ({be:,.0f}$)".replace(",","."))

    # ingressi (alert)
    can_long  = up   and (not RSI_CONFIRM or (r is not None and r>=RSI_LONG_MIN))  and (not MACD_CONFIRM or macd_long)  and (roc>=ROC_MIN_PCT)  and (lastClose>hh) and v_spike
    can_short = down and (not RSI_CONFIRM or (r is not None and r<=RSI_SHORT_MAX)) and (not MACD_CONFIRM or macd_short) and (-roc>=ROC_MIN_PCT) and (lastClose<ll) and v_spike

    now=time.time()
    if P.side is None:
        if can_long and a:
            e=plan_long(); 
            if e:
                P.side="long"; P.entry,P.sl,P.tp1,P.tp2=e; P.hit=False; P.ext=None; P.last_ts=now
                tg_send(f"🚀 LONG {sym}\nPx {pr:,.0f}$  |  Trigger {e[0]:,.0f}\nSL {e[1]:,.0f}  TP {e[2]:,.0f}/{e[3]:,.0f}  Lev x{DEFAULT_LEV}".replace(",","."))

        elif can_short and a:
            e=plan_short();
            if e:
                P.side="short"; P.entry,P.sl,P.tp1,P.tp2=e; P.hit=False; P.ext=None; P.last_ts=now
                tg_send(f"⚡ SHORT {sym}\nPx {pr:,.0f}$  |  Trigger {e[0]:,.0f}\nSL {e[1]:,.0f}  TP {e[2]:,.0f}/{e[3]:,.0f}  Lev x{DEFAULT_LEV}".replace(",","."))

def main():
    tg_send("🟢 Zeta BOT avviato (15m).")
    while True:
        try:
            vol=cmc_vol(SYMBOLS)
            for s in SYMBOLS: process(s, vol)
        except Exception as e:
            tg_send(f"⚠️ errore: {e.__class__.__name__}")
        time.sleep(LOOP_SECONDS)

if __name__=="__main__":
    main()
