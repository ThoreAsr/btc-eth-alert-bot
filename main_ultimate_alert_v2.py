#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
2 Brothers — Ultimate Alerts (TOP + VWAP Batman & Robin Edition)
- Prezzi: MEXC/Binance con mirror & retry
- Volumi 24h: CoinMarketCap
- Indicatori: EMA(15/50), RSI, MACD, ATR dinamico, momentum, soft-breakout, spike volumi
- VWAP filter: Day/Week/Month + Rolling 7D (dev. std) come conferma opzionale
- Pre-Alert velocità + Big-Move (Δ) con cooldown
- Uscite: TP1 (SL->BE), TP2, STOP
- Grafici PNG con cooldown (Apple Watch OK)
- Branding: "2 Brothers" + logo Batman&Robin via LOGO_URL
"""

import os, io, time, random, math
from typing import List, Tuple, Dict, Optional
import requests

# ========================= ENV / CONFIG =========================
def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, str(default)).strip().lower()
    return v in ("1", "true", "yes", "y", "on")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("Token", ""))
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", os.environ.get("Chat_Id", ""))

# CoinMarketCap key (accetta entrambi i nomi)
CMC_API_KEY = os.environ.get("CMC_API_KEY", os.environ.get("COINMARKETCAP_API_KEY", ""))

BRAND_NAME = os.environ.get("BRAND_NAME", "2 Brothers")
LOGO_URL   = os.environ.get("LOGO_URL", "").strip()

SYMBOLS       = [s.strip().upper() for s in os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
LOOP_SECONDS  = int(os.environ.get("LOOP_SECONDS", "240"))

SEND_HEARTBEAT= _env_bool("SEND_HEARTBEAT", False)
INTERVAL_MIN  = int(os.environ.get("INTERVAL_MINUTES", "15"))

CHART_ON_BREAKOUT  = _env_bool("CHART_ON_BREAKOUT", True)
CHART_ON_SPIKE     = _env_bool("CHART_ON_SPIKE", True)
CHART_COOLDOWN_MIN = int(os.environ.get("CHART_COOLDOWN_MIN", "45"))

DEFAULT_LEVERAGE   = float(os.environ.get("DEFAULT_LEVERAGE", "3"))

# Conferme classiche
RSI_CONFIRMATION = _env_bool("RSI_CONFIRMATION", True)
RSI_LONG_MIN     = float(os.environ.get("RSI_LONG_MIN", "55"))
RSI_SHORT_MAX    = float(os.environ.get("RSI_SHORT_MAX", "45"))
MACD_CONFIRMATION= _env_bool("MACD_CONFIRMATION", True)
MACD_FAST        = int(os.environ.get("MACD_FAST", "12"))
MACD_SLOW        = int(os.environ.get("MACD_SLOW", "26"))
MACD_SIGNAL      = int(os.environ.get("MACD_SIGNAL", "9"))

# ATR plan
USE_ATR_PLAN = _env_bool("USE_ATR_PLAN", True)
ATR_PERIOD   = int(os.environ.get("ATR_PERIOD", "14"))
ATR_MULT_SL  = float(os.environ.get("ATR_MULT_SL", "1.5"))
ATR_MULT_TP1 = float(os.environ.get("ATR_MULT_TP1", "1.0"))
ATR_MULT_TP2 = float(os.environ.get("ATR_MULT_TP2", "2.0"))
ATR_MAX_LEV_PC = float(os.environ.get("ATR_MAX_LEV_PC", "1.8"))  # %

MIN_ENTRY_COOLDOWN = int(os.environ.get("MIN_ENTRY_COOLDOWN_MIN", "15")) * 60

# Dinamica ingresso
SOFT_BREAKOUT_PCT     = float(os.environ.get("SOFT_BREAKOUT_PCT", "0.12"))
REQUIRE_CANDLES_ABOVE = int(os.environ.get("REQUIRE_CANDLES_ABOVE", "1"))
MOMENTUM_15M_PCT      = float(os.environ.get("MOMENTUM_15M_PCT", "0.7"))
MOMENTUM_1H_PCT       = float(os.environ.get("MOMENTUM_1H_PCT", "1.8"))
OVERRIDE_VOLUME_SPIKE = _env_bool("OVERRIDE_VOLUME_SPIKE", True)
VOLUME_SPIKE_STRONG   = float(os.environ.get("VOLUME_SPIKE_STRONG", "60"))

# Big-Move informativo
BIG_MOVE_USD_BTC      = float(os.environ.get("BIG_MOVE_USD_BTC", "2000"))
BIG_MOVE_USD_ETH      = float(os.environ.get("BIG_MOVE_USD_ETH", "120"))
BIG_MOVE_LOOKBACK_MIN = int(os.environ.get("BIG_MOVE_LOOKBACK_MIN", "60"))
BIG_MOVE_COOLDOWN_MIN = int(os.environ.get("BIG_MOVE_COOLDOWN_MIN", "45"))

# Pre-Alert predittivo
FAST_WATCH               = _env_bool("FAST_WATCH", True)
FAST_LOOP_SECONDS        = int(os.environ.get("FAST_LOOP_SECONDS", "45"))
PREALERT_COOLDOWN_MIN    = int(os.environ.get("PREALERT_COOLDOWN_MIN", "20"))
BIG_MOVE_EARLY_FRACTION  = float(os.environ.get("BIG_MOVE_EARLY_FRACTION", "0.6"))
VELOCITY_USD_PER_MIN_BTC = float(os.environ.get("VELOCITY_USD_PER_MIN_BTC", "400"))
VELOCITY_USD_PER_MIN_ETH = float(os.environ.get("VELOCITY_USD_PER_MIN_ETH", "25"))

# VWAP filter
VWAP_CONFIRMATION   = _env_bool("VWAP_CONFIRMATION", True)
CONFLUENCE_N        = int(os.environ.get("CONFLUENCE_N", "2"))
BANDS_STDEV_MULT    = float(os.environ.get("BANDS_STDEV_MULT", "1.0"))

# --- Floors per TP (percentuali e USD) ---
MIN_TP1_PCT_BTC = float(os.environ.get("MIN_TP1_PCT_BTC", "0.15"))
MIN_TP2_PCT_BTC = float(os.environ.get("MIN_TP2_PCT_BTC", "0.35"))
MIN_TP1_PCT_ETH = float(os.environ.get("MIN_TP1_PCT_ETH", "0.20"))
MIN_TP2_PCT_ETH = float(os.environ.get("MIN_TP2_PCT_ETH", "0.45"))

MIN_TP1_USD_BTC = float(os.environ.get("MIN_TP1_USD_BTC", "80"))
MIN_TP2_USD_BTC = float(os.environ.get("MIN_TP2_USD_BTC", "180"))
MIN_TP1_USD_ETH = float(os.environ.get("MIN_TP1_USD_ETH", "6"))
MIN_TP2_USD_ETH = float(os.environ.get("MIN_TP2_USD_ETH", "14"))

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nelle Environment Variables.")

# =================== HTTP ===================
MEXC_BASES = ["https://api.mexc.com", "https://www.mexc.com"]
BINANCE_BASES = [
    "https://api.binance.com","https://api1.binance.com","https://api2.binance.com",
    "https://api3.binance.com","https://api-gcp.binance.com","https://data-api.binance.vision"
]
CACHE: Dict[str, dict] = {}
TTL_15M = 300
TTL_30M = 900
TTL_CMC = 900
LAST_RATE_WARN = {"ts": 0}

def _jitter(a=0.25, b=0.7): time.sleep(random.uniform(a, b))

def http_get(url: str, params: dict, timeout=15, retries=3, backoff=2.0, headers=None):
    last=None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep((i+1)*backoff); continue
            r.raise_for_status()
            return r
        except Exception as e:
            last=e; time.sleep((i+1)*0.5)
    if last: raise last

def _json_with_fallback(paths: List[tuple], params: dict, timeout=15, headers=None):
    last_err=None
    for base, path in paths:
        try:
            _jitter(0.15,0.5)
            r = http_get(f"{base}{path}", params=params, timeout=timeout, headers=headers)
            return r.json()
        except Exception as e:
            last_err=e
    raise last_err

# =================== FETCHERS ===================
def fetch_price(symbol: str) -> float:
    paths=[(b,"/api/v3/ticker/price") for b in MEXC_BASES] + [(b,"/api/v3/ticker/price") for b in BINANCE_BASES]
    data = _json_with_fallback(paths, {"symbol": symbol}, timeout=8)
    return float(data["price"])

def fetch_klines_cached(symbol: str, interval: str, limit: int, ttl: int) -> list:
    key=f"{symbol}_{interval}"; now=time.time()
    c=CACHE.get(key)
    if c and now-c["ts"]<ttl: return c["data"]
    paths=[(b,"/api/v3/klines") for b in MEXC_BASES] + [(b,"/api/v3/klines") for b in BINANCE_BASES]
    data=_json_with_fallback(paths, {"symbol":symbol,"interval":interval,"limit":limit}, timeout=12)
    CACHE[key]={"ts":now,"data":data}; return data

def fetch_cmc_volumes_cached(symbols: List[str]) -> Dict[str, float]:
    now=time.time(); c=CACHE.get("CMC_VOL")
    if c and now-c["ts"]<TTL_CMC: return c["data"]
    if not CMC_API_KEY: return {}
    try:
        bases=sorted({s.replace("USDT","").replace("USD","") for s in symbols})
        url="https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
        headers={"X-CMC_PRO_API_KEY": CMC_API_KEY}
        _jitter(0.2,0.6)
        r=http_get(url, {"symbol":",".join(bases),"convert":"USD"}, timeout=12, headers=headers)
        data=r.json().get("data",{}); out={}
        for b in bases:
            try: out[b]=float(data[b][0]["quote"]["USD"]["volume_24h"])
            except Exception: pass
        CACHE["CMC_VOL"]={"ts":now,"data":out}; return out
    except Exception:
        return c["data"] if c else {}

# =================== INDICATORS ===================
def ema(vals: List[float], length: int) -> List[float]:
    if not vals or length<=0 or len(vals)<length: return []
    k=2/(length+1); out=[sum(vals[:length])/length]
    for v in vals[length:]: out.append(v*k + out[-1]*(1-k))
    return [None]*(len(vals)-len(out)) + out

def trend_from_ema(closes: List[float], fast=15, slow=50) -> str:
    efast, eslow = ema(closes, fast), ema(closes, slow)
    if not efast or not eslow or efast[-1] is None or eslow[-1] is None: return "n/d"
    return "rialzo" if efast[-1] > eslow[-1] else ("ribasso" if efast[-1] < eslow[-1] else "neutro")

def rsi(values: List[float], period: int=14) -> Optional[float]:
    if len(values)<period+1: return None
    gains=losses=0.0
    for i in range(-period,0):
        d=values[i]-values[i-1]
        gains+=max(d,0); losses+=max(-d,0)
    if losses==0: return 100.0
    rs=(gains/period)/(losses/period); return 100 - 100/(1+rs)

def macd(values: List[float], fast=12, slow=26, signal=9) -> Tuple[Optional[float], Optional[float]]:
    if len(values)<slow+signal: return None,None
    ema_fast=ema(values,fast); ema_slow=ema(values,slow)
    line=[]
    for i in range(len(values)):
        if ema_fast[i] is None or ema_slow[i] is None: line.append(None)
        else: line.append(ema_fast[i]-ema_slow[i])
    valid=[m for m in line if m is not None]
    if len(valid)<signal: return None,None
    k=2/(signal+1); sig=[sum(valid[:signal])/signal]
    for v in valid[signal:]: sig.append(v*k + sig[-1]*(1-k))
    return valid[-1], sig[-1]

def true_range(h,l,prev_close): return max(h-l, abs(h-prev_close), abs(l-prev_close))
def atr_from_klines(klines: list, period: int=14) -> Optional[float]:
    if len(klines)<period+1: return None
    trs=[]; prev=float(klines[-period-1][4])
    for k in klines[-period:]:
        h=float(k[2]); l=float(k[3]); trs.append(true_range(h,l,prev)); prev=float(k[4])
    return sum(trs)/period if trs else None

def pct_change(v_now: float, v_prev: float) -> Optional[float]:
    if v_prev==0: return None
    return (v_now-v_prev)/v_prev*100.0

# ===== VWAP =====
def _sym_base(symbol: str)->str: return symbol.replace("USDT","").replace("USD","")
def typical_price(h,l,c)->float: return (h+l+c)/3.0

def anchored_vwap(times, highs, lows, closes, vols, anchor: str) -> float:
    import datetime as dt
    if not times: return float("nan")
    ts_last=times[-1]//1000; last=dt.datetime.utcfromtimestamp(ts_last)
    def same(ms):
        d=dt.datetime.utcfromtimestamp(ms//1000)
        if anchor=="D": return d.date()==last.date()
        if anchor=="W": return d.isocalendar()[0:2]==last.isocalendar()[0:2]
        if anchor=="M": return (d.year,d.month)==(last.year,last.month)
        return True
    start=0
    for i in range(len(times)-1,-1,-1):
        if not same(times[i]): start=i+1; break
    pv=v=pp=0.0
    for i in range(start, len(times)):
        tp=typical_price(highs[i], lows[i], closes[i]); vol=vols[i]
        pv+=tp*vol; v+=vol; pp+=(tp*tp)*vol
    if v<=0: return float("nan")
    return pv/v

def rolling_vwap7_bands(highs, lows, closes, vols, stdev_mult=1.0):
    n=len(closes); win=672
    if n<win: return float("nan"), float("nan"), float("nan")
    s=n-win; pv=v=pp=0.0
    for i in range(s, n):
        tp=typical_price(highs[i], lows[i], closes[i]); vol=vols[i]
        pv+=tp*vol; v+=vol; pp+=(tp*tp)*vol
    if v<=0: return float("nan"), float("nan"), float("nan")
    vw=pv/v; var=max(0.0, pp/v - vw*vw); sd=math.sqrt(var)
    return vw, vw+stdev_mult*sd, vw-stdev_mult*sd

def vwap_filter_signal(times, highs, lows, closes, vols):
    vD=anchored_vwap(times,highs,lows,closes,vols,"D")
    vW=anchored_vwap(times,highs,lows,closes,vols,"W")
    vM=anchored_vwap(times,highs,lows,closes,vols,"M")
    rv,rU,rL=rolling_vwap7_bands(highs,lows,closes,vols,BANDS_STDEV_MULT)
    price=float(closes[-1])
    above=int(price>vD)+int(price>vW)+int(price>vM)
    below=int(price<vD)+int(price<vW)+int(price<vM)
    confl_long  = above>=CONFLUENCE_N
    confl_short = below>=CONFLUENCE_N
    bounce_long  = (not math.isnan(rL) and closes[-2]<rL and closes[-1]>rL)
    bounce_short = (not math.isnan(rU) and closes[-2]>rU and closes[-1]<rU)
    # slope M approx 1d
    look=96
    def vwapM_at(idx):
        if idx<100: return float("nan")
        return anchored_vwap(times[:idx], highs[:idx], lows[:idx], closes[:idx], vols[:idx], "M")
    idx=len(closes); prev=max(0, idx-look)
    vM_prev=vwapM_at(prev); slope_up=(not math.isnan(vM) and not math.isnan(vM_prev) and (vM - vM_prev)>=0)
    slope_down=(not math.isnan(vM) and not math.isnan(vM_prev) and (vM - vM_prev)<=0)
    vol_ok = (len(vols)>=20 and vols[-1] > sum(vols[-20:])/20.0)
    long_ok  = ((confl_long and slope_up and vol_ok) or bounce_long)
    short_ok = ((confl_short and slope_down and vol_ok) or bounce_short)
    info={"vD":vD,"vW":vW,"vM":vM,"rv":rv,"rU":rU,"rL":rL,"conf_above":above,"conf_below":below,"vol_ok":vol_ok}
    return long_ok, short_ok, info

# =================== MESSAGGI ===================
def round_k(x: float)->str:
    step=100 if x>=10000 else 50; y=round(x/step)*step
    if y>=1000: return f"{int(y/1000)}k" if y%1000==0 else f"{y/1000:.1f}k"
    return f"{int(y)}"
def fmt_price(p: float)->str:
    try: return f"{p:,.0f}$".replace(",", ".")
    except Exception: return f"{p:.2f}$"
def fmt_billions(x: float)->str:
    try: return f"{x/1e9:.1f}B"
    except Exception: return "n/d"
def brand_prefix()->str: return f"🦇 {BRAND_NAME}"

def chat_ids()->List[str]: return [cid.strip() for cid in TELEGRAM_CHAT_ID.strip().split(",") if cid.strip()]

def tg_send(text: str):
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for cid in chat_ids():
        try: requests.post(url, data={"chat_id":cid, "text":text}, timeout=15).raise_for_status()
        except Exception: pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def tg_photo(img_or_url, caption: str=""):
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    for cid in chat_ids():
        try:
            if isinstance(img_or_url, (bytes, bytearray)):
                requests.post(url, data={"chat_id":cid, "caption":caption},
                              files={"photo":("chart.png", img_or_url)}, timeout=30).raise_for_status()
            else:
                requests.post(url, data={"chat_id":cid, "photo":img_or_url, "caption":caption}, timeout=15).raise_for_status()
        except Exception: pass

def make_chart_png(symbol, k15, res, sup, price)->bytes:
    closes=[float(k[4]) for k in k15][-100:]; xs=list(range(len(closes)))
    plt.figure(figsize=(6,3), dpi=200)
    plt.plot(xs, closes)
    plt.axhline(res, linestyle="--"); plt.axhline(sup, linestyle="--")
    plt.title(f"{symbol}  |  {fmt_price(price)}"); plt.tight_layout()
    buf=io.BytesIO(); plt.savefig(buf, format="png"); plt.close(); buf.seek(0); return buf.read()

# =================== STATE ===================
class Position:
    def __init__(self):
        self.side=None; self.entry=self.sl=self.tp1=self.tp2=0.0; self.hit_tp1=False; self.last_entry_ts=0.0
class State:
    def __init__(self):
        self.last_side={}; self.last_hb_minute=-1; self.last_chart_ts={}; self.pos={}; self.last_bigmove_ts={}
        self.fast_anchor={}; self.fast_last={}; self.last_prealert_ts={}
STATE=State()

def side_vs_band(p,sup,res)->str:
    if p>res: return "above"
    if p<sup: return "below"
    return "between"

# =================== CORE HELPERS ===================
def volume_spike_15m(vols: List[float], lookback=20)->Tuple[float,str]:
    if len(vols)<lookback+1: return 0.0,"n/d"
    avg=sum(vols[-lookback-1:-1])/lookback; last=vols[-1]
    if avg<=0: return 0.0,"n/d"
    pct=(last/avg - 1.0)*100.0
    if pct>=100: label="↑ forte"
    elif pct>=25: label="↑"
    elif pct<=-25: label="↓"
    else: label="≈"
    return pct,label

# ---- TP floors helpers + op-plan PATCH ----
def _tp_floors(symbol: str, price: float) -> Tuple[float, float]:
    base = _sym_base(symbol)
    if base == "BTC":
        f1 = max(MIN_TP1_PCT_BTC/100.0 * price, MIN_TP1_USD_BTC)
        f2 = max(MIN_TP2_PCT_BTC/100.0 * price, MIN_TP2_USD_BTC)
    else:  # ETH e altri
        f1 = max(MIN_TP1_PCT_ETH/100.0 * price, MIN_TP1_USD_ETH)
        f2 = max(MIN_TP2_PCT_ETH/100.0 * price, MIN_TP2_USD_ETH)
    return f1, f2

def op_plan_long(res, sup, atr, price, symbol=""):
    entry = res
    f1, f2 = _tp_floors(symbol, price)
    if USE_ATR_PLAN and atr:
        sl  = entry - ATR_MULT_SL  * atr
        tp1 = entry + max(ATR_MULT_TP1 * atr, f1)
        tp2 = entry + max(ATR_MULT_TP2 * atr, f2)
    else:
        sl  = sup * 0.998
        R1  = max(entry - sl, f1)
        R2  = max(2 * (entry - sl), f2)
        tp1 = entry + R1
        tp2 = entry + R2
    return entry, sl, tp1, tp2

def op_plan_short(res, sup, atr, price, symbol=""):
    entry = sup
    f1, f2 = _tp_floors(symbol, price)
    if USE_ATR_PLAN and atr:
        sl  = entry + ATR_MULT_SL  * atr
        tp1 = entry - max(ATR_MULT_TP1 * atr, f1)
        tp2 = entry - max(ATR_MULT_TP2 * atr, f2)
    else:
        sl  = res * 1.002
        R1  = max(sl - entry, f1)
        R2  = max(2 * (sl - entry), f2)
        tp1 = entry - R1
        tp2 = entry - R2
    return entry, sl, tp1, tp2

def suggested_leverage(atr, price)->int:
    base=int(DEFAULT_LEVERAGE)
    if not atr or price<=0: return base
    atr_pct=(atr/price)*100.0
    return max(1, base-1) if atr_pct>ATR_MAX_LEV_PC else base

# =================== PROCESS ===================
def process_symbol(symbol: str, cmc_vols: Dict[str,float]):
    k15=fetch_klines_cached(symbol,"15m",200,TTL_15M); _jitter(0.05,0.2)
    k30=fetch_klines_cached(symbol,"30m",200,TTL_30M)

    closes15=[float(k[4]) for k in k15]
    highs15=[float(k[2]) for k in k15]
    lows15 =[float(k[3]) for k in k15]
    vols15 =[float(k[5]) for k in k15]
    closes30=[float(k[4]) for k in k30]

    res=max(highs15[-48:]); sup=min(lows15[-48:])
    tr15, tr30 = trend_from_ema(closes15), trend_from_ema(closes30)
    rsi15=rsi(closes15,14)
    macd_line, macd_sig=macd(closes15, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    macd_ok_long  = (macd_line is not None and macd_sig is not None and macd_line>macd_sig)
    macd_ok_short = (macd_line is not None and macd_sig is not None and macd_line<macd_sig)

    _jitter(0.05,0.2)
    price=fetch_price(symbol)

    sp_pct, sp_lbl = volume_spike_15m(vols15,20)
    base=_sym_base(symbol); vol24h = cmc_vols.get(base)
    atr=atr_from_klines(k15, ATR_PERIOD); lev=suggested_leverage(atr, price)

    now_side=side_vs_band(price,sup,res); prev_side=STATE.last_side.get(symbol,"between"); STATE.last_side[symbol]=now_side

    # heartbeat
    if SEND_HEARTBEAT:
        now_min=int(time.time()//60)
        if now_min%INTERVAL_MIN==0 and STATE.last_hb_minute!=now_min:
            STATE.last_hb_minute=now_min
            hb=(f"{brand_prefix()} | 🫀 {symbol}\n"
                f"💵 {fmt_price(price)} | 15m:{tr15}/30m:{tr30} R:{round_k(res)} S:{round_k(sup)}  🔊{sp_lbl}")
            if LOGO_URL: tg_photo(LOGO_URL, caption=hb)
            else: tg_send(hb)

    # setup su cambio banda → STATO: ATTESA
    if prev_side!=now_side:
        # trigger atteso: se siamo sopra, probabile attesa short (sup); se sotto, attesa long (res)
        trigger_txt = fmt_price(res) if now_side!="above" else fmt_price(sup)
        txt=(f"{brand_prefix()} | 📉 {symbol}\n"
             f"📍 STATO: ATTESA (trigger {trigger_txt})\n"
             f"💵 {fmt_price(price)}\n"
             f"📈 15m:{tr15} | 30m:{tr30}\n"
             f"🔑 R:{round_k(res)} | S:{round_k(sup)}\n"
             f"🔊 Vol15m: {sp_lbl} ({sp_pct:.0f}%) | 24h:{fmt_billions(vol24h)}\n"
             f"⚡ x{lev}")
        if LOGO_URL: tg_photo(LOGO_URL, caption=txt)
        else: tg_send(txt)

    # Big move
    n_back=max(1, BIG_MOVE_LOOKBACK_MIN//15)
    ref_close=closes15[-n_back-1] if len(closes15)>n_back else closes15[0]
    move_usd=price-ref_close; move_abs=abs(move_usd)
    big_thr=BIG_MOVE_USD_BTC if base=="BTC" else (BIG_MOVE_USD_ETH if base=="ETH" else BIG_MOVE_USD_BTC)
    now_ts=time.time(); last_ts=STATE.last_bigmove_ts.get(symbol,0.0)
    if move_abs>=big_thr and (now_ts-last_ts)>=BIG_MOVE_COOLDOWN_MIN*60:
        dir_emoji="🚀" if move_usd>0 else "🩸"
        pct=pct_change(price,ref_close); pct_txt=f"{pct:.2f}%" if pct is not None else "n/d"
        msg=(f"{brand_prefix()} | {dir_emoji} BIG MOVE [{symbol}] {BIG_MOVE_LOOKBACK_MIN}m\n"
             f"Δ {fmt_price(ref_close)} → {fmt_price(price)}  ({'+' if move_usd>0 else ''}{fmt_price(move_usd)})  ~{pct_txt}\n"
             f"Trend 15m:{tr15} / 30m:{tr30}")
        if LOGO_URL: tg_photo(LOGO_URL, caption=msg)
        else: tg_send(msg)
        try:
            last_chart=STATE.last_chart_ts.get(symbol,0.0)
            if time.time()-last_chart>=CHART_COOLDOWN_MIN*60:
                img=make_chart_png(symbol,k15,res,sup,price)
                tg_photo(img, caption=f"{symbol} — Big Move {BIG_MOVE_LOOKBACK_MIN}m")
                STATE.last_chart_ts[symbol]=time.time()
        except Exception: pass
        STATE.last_bigmove_ts[symbol]=now_ts

    # posizione
    if symbol not in STATE.pos: STATE.pos[symbol]=Position()
    P=STATE.pos[symbol]
    eL,sL,t1L,t2L = op_plan_long(res,sup,atr,price,symbol)
    eS,sS,t1S,t2S = op_plan_short(res,sup,atr,price,symbol)

    # exits
    if P.side=="long":
        if price<=P.sl:
            tg_send(f"{brand_prefix()} | 🏁 EXIT [{symbol}] — STOP (long) a {fmt_price(price)}"); STATE.pos[symbol]=Position()
        elif not P.hit_tp1 and price>=P.tp1:
            P.hit_tp1=True; P.sl=max(P.sl, P.entry); tg_send(f"{brand_prefix()} | 🏁 EXIT [{symbol}] — TP1 (long) — SL→BE")
        elif price>=P.tp2:
            tg_send(f"{brand_prefix()} | 🏁 EXIT [{symbol}] — TP2 (long)"); STATE.pos[symbol]=Position()
    elif P.side=="short":
        if price>=P.sl:
            tg_send(f"{brand_prefix()} | 🏁 EXIT [{symbol}] — STOP (short) a {fmt_price(price)}"); STATE.pos[symbol]=Position()
        elif not P.hit_tp1 and price<=P.tp1:
            P.hit_tp1=True; P.sl=min(P.sl, P.entry); tg_send(f"{brand_prefix()} | 🏁 EXIT [{symbol}] — TP1 (short) — SL→BE")
        elif price<=P.tp2:
            tg_send(f"{brand_prefix()} | 🏁 EXIT [{symbol}] — TP2 (short)"); STATE.pos[symbol]=Position()

    # VWAP filter
    times=[int(k[0]) for k in k15]
    long_vwap_ok, short_vwap_ok, vinfo = vwap_filter_signal(times, highs15, lows15, closes15, vols15)

    # ingressi
    soft_long  = price > res * (1.0 + SOFT_BREAKOUT_PCT/100.0)
    soft_short = price < sup * (1.0 - SOFT_BREAKOUT_PCT/100.0)
    above_count = sum(1 for c in closes15[-REQUIRE_CANDLES_ABOVE:] if c>res) if REQUIRE_CANDLES_ABOVE>0 else 1
    below_count = sum(1 for c in closes15[-REQUIRE_CANDLES_ABOVE:] if c<sup) if REQUIRE_CANDLES_ABOVE>0 else 1
    closes_ok_long  = (REQUIRE_CANDLES_ABOVE<=1) or (above_count>=REQUIRE_CANDLES_ABOVE)
    closes_ok_short = (REQUIRE_CANDLES_ABOVE<=1) or (below_count>=REQUIRE_CANDLES_ABOVE)
    m15 = pct_change(closes15[-1], closes15[-2]) if len(closes15)>=2 else None
    m1h = pct_change(closes15[-1], closes15[-5]) if len(closes15)>=5 else None
    momentum_long  = ((m15 is not None and m15>=MOMENTUM_15M_PCT) or (m1h is not None and m1h>=MOMENTUM_1H_PCT))
    momentum_short = ((m15 is not None and m15<=-MOMENTUM_15M_PCT) or (m1h is not None and m1h<=-MOMENTUM_1H_PCT))
    spike_override = OVERRIDE_VOLUME_SPIKE and (sp_lbl=="↑ forte" or sp_pct>=VOLUME_SPIKE_STRONG)

    base_long  = ( (price>eL) or (soft_long and closes_ok_long) or momentum_long or spike_override ) and tr15=="rialzo" and tr30 in ("rialzo","neutro")
    base_short = ( (price<eS) or (soft_short and closes_ok_short) or momentum_short or spike_override ) and tr15=="ribasso" and tr30 in ("ribasso","neutro")

    can_long, can_short = base_long, base_short
    if RSI_CONFIRMATION and rsi15 is not None:
        can_long  = can_long  and rsi15>=RSI_LONG_MIN
        can_short = can_short and rsi15<=RSI_SHORT_MAX
    if MACD_CONFIRMATION:
        can_long  = can_long  and macd_ok_long
        can_short = can_short and macd_ok_short
    if VWAP_CONFIRMATION:
        can_long  = can_long  and long_vwap_ok
        can_short = can_short and short_vwap_ok

    # entry (messaggi in IT con STATO: ENTRATA)
    now_ts=time.time()
    if P.side is None:
        if can_long and now_ts-P.last_entry_ts>MIN_ENTRY_COOLDOWN:
            P.side="long"; P.entry=eL; P.sl=sL; P.tp1=t1L; P.tp2=t2L; P.hit_tp1=False; P.last_entry_ts=now_ts
            msg=(f"{brand_prefix()} | 🚨 LONG [{symbol}]\n"
                 f"📍 STATO: ENTRATA\n"
                 f"💵 {fmt_price(price)} | trigger {fmt_price(eL)} | ⚡x{suggested_leverage(atr,price)}\n"
                 f"🛡️ SL {fmt_price(sL)}  🎯 {fmt_price(t1L)} / {fmt_price(t2L)}\n"
                 f"VWAP D:{fmt_price(vinfo['vD'])} W:{fmt_price(vinfo['vW'])} M:{fmt_price(vinfo['vM'])}  "
                 f"Conf:{vinfo['conf_above']}/3  Vol✓:{'Sì' if vinfo['vol_ok'] else 'No'}")
            if LOGO_URL: tg_photo(LOGO_URL, caption=msg)
            else: tg_send(msg)
            try: img=make_chart_png(symbol,k15,res,sup,price); tg_photo(img, caption=f"{symbol} — LONG setup")
            except Exception: pass

        elif can_short and now_ts-P.last_entry_ts>MIN_ENTRY_COOLDOWN:
            P.side="short"; P.entry=eS; P.sl=sS; P.tp1=t1S; P.tp2=t2S; P.hit_tp1=False; P.last_entry_ts=now_ts
            msg=(f"{brand_prefix()} | 🚨 SHORT [{symbol}]\n"
                 f"📍 STATO: ENTRATA\n"
                 f"💵 {fmt_price(price)} | trigger {fmt_price(eS)} | ⚡x{suggested_leverage(atr,price)}\n"
                 f"🛡️ SL {fmt_price(sS)}  🎯 {fmt_price(t1S)} / {fmt_price(t2S)}\n"
                 f"VWAP D:{fmt_price(vinfo['vD'])} W:{fmt_price(vinfo['vW'])} M:{fmt_price(vinfo['vM'])}  "
                 f"Conf:{vinfo['conf_below']}/3  Vol✓:{'Sì' if vinfo['vol_ok'] else 'No'}")
            if LOGO_URL: tg_photo(LOGO_URL, caption=msg)
            else: tg_send(msg)
            try: img=make_chart_png(symbol,k15,res,sup,price); tg_photo(img, caption=f"{symbol} — SHORT setup")
            except Exception: pass

    # grafico su eventi forti
    want_chart=False
    if CHART_ON_BREAKOUT and prev_side!=now_side: want_chart=True
    if CHART_ON_SPIKE and sp_lbl=="↑ forte":      want_chart=True
    if want_chart:
        last=STATE.last_chart_ts.get(symbol,0.0)
        if time.time()-last>=CHART_COOLDOWN_MIN*60:
            try:
                img=make_chart_png(symbol,k15,res,sup,price)
                tg_photo(img, caption=f"{symbol} | R:{round_k(res)} S:{round_k(sup)}")
                STATE.last_chart_ts[symbol]=time.time()
            except Exception: pass

# =================== FAST WATCH (PRE-ALERT) ===================
def _vel_threshold(symbol: str)->float:
    return VELOCITY_USD_PER_MIN_BTC if _sym_base(symbol)=="BTC" else VELOCITY_USD_PER_MIN_ETH
def _big_thr_usd(symbol: str)->float:
    base=_sym_base(symbol)
    return BIG_MOVE_USD_BTC if base=="BTC" else (BIG_MOVE_USD_ETH if base=="ETH" else BIG_MOVE_USD_BTC)

def fast_watcher_once(symbol: str):
    try: price=fetch_price(symbol)
    except Exception: return
    now=time.time()
    look=BIG_MOVE_LOOKBACK_MIN*60
    anc_p, anc_t = STATE.fast_anchor.get(symbol,(price,now))
    if now-anc_t>look: anc_p,anc_t=price,now; STATE.fast_anchor[symbol]=(anc_p,anc_t)
    last_p,last_t=STATE.fast_last.get(symbol,(price,now))
    dt=max(1.0, now-last_t); vel=abs(price-last_p)/dt*60.0; STATE.fast_last[symbol]=(price,now)
    move_abs=abs(price-anc_p); need=_big_thr_usd(symbol)*BIG_MOVE_EARLY_FRACTION; thr=_vel_threshold(symbol)
    last_pre=STATE.last_prealert_ts.get(symbol,0.0)
    if (vel>=thr) and (move_abs>=need) and (now-last_pre>=PREALERT_COOLDOWN_MIN*60):
        dir_emoji="⚡🚀" if price>=anc_p else "⚡🩸"; covered=f"{int(BIG_MOVE_EARLY_FRACTION*100)}%"
        msg=(f"{brand_prefix()} | {dir_emoji} PRE-ALERT [{symbol}] — accelera\n"
             f"da {fmt_price(anc_p)} → {fmt_price(price)} (≈{covered} del big-move)\n"
             f"Vel ≈ {vel:.0f}$/min")
        if LOGO_URL: tg_photo(LOGO_URL, caption=msg)
        else: tg_send(msg)
        STATE.last_prealert_ts[symbol]=now

# =================== MAIN LOOP ===================
def main_loop():
    try:
        start_msg=f"{brand_prefix()} | 🟢 Bot avviato — {', '.join(SYMBOLS)} (15m/30m) + VWAP"
        if LOGO_URL: tg_photo(LOGO_URL, caption=start_msg)
        else: tg_send(start_msg)
    except Exception: pass

    last_fast=0.0
    while True:
        now=time.time()
        if FAST_WATCH and (now-last_fast>=FAST_LOOP_SECONDS):
            for s in SYMBOLS: fast_watcher_once(s)
            last_fast=now
        try:
            cmc=fetch_cmc_volumes_cached(SYMBOLS)
            for s in SYMBOLS: process_symbol(s, cmc)
        except requests.HTTPError as e:
            code=getattr(e.response,"status_code",None)
            if code in (429,451):
                cur=time.time()
                if cur-LAST_RATE_WARN["ts"]>600:
                    tg_send(f"{brand_prefix()} | ⚠️ Rate limit {code}: rallento…")
                    LAST_RATE_WARN["ts"]=cur
            else:
                tg_send(f"{brand_prefix()} | ⚠️ Errore dati: HTTP {code or ''}".strip())
        except Exception:
            pass
        time.sleep(LOOP_SECONDS)

if __name__=="__main__":
    main_loop()
