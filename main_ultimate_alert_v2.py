#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2Brothers — VWAP+ Pro Bot (Telegram • iPhone/Apple Watch)
Licenza: MPL-2.0
"""

import os, io, math, json, time, logging
from typing import Dict, List, Optional, Tuple
import requests, numpy as np, pandas as pd
import matplotlib.pyplot as plt

# ================== BRAND / LOGO ==================
BRAND = "2Brothers"
LOGO_PREFIX = "🟩 2Brothers"

# ================== SECRETI INLINE (INSERITI) ==================
SECRETS_INLINE = {
    "TELEGRAM_BOT_TOKEN": "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA",
    "TELEGRAM_CHAT_ID":   "-1002181919588",
    "COINMARKETCAP_API_KEY": "e1bf46bf-1e42-4c30-8847-c011f772dcc8",
}
# ===================================================================

# ================== CONFIG BASE ===================
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
TIMEFRAMES_MIN = [15, 30]
LEGACY_TF_MIN  = 15

TZ_DISPLAY = "Europe/Rome"
ENV_TG_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_TG_CHAT  = "TELEGRAM_CHAT_ID"
ENV_CMC_KEY  = "COINMARKETCAP_API_KEY"

TELEGRAM_BOT_TOKEN_FALLBACK = SECRETS_INLINE.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID_FALLBACK   = SECRETS_INLINE.get("TELEGRAM_CHAT_ID", "")
COINMARKETCAP_API_KEY_FALLBACK = SECRETS_INLINE.get("COINMARKETCAP_API_KEY", "")

# ---- Parametri Legacy ----
SOFT_BREAKOUT_PCT      = 0.10
REQUIRE_CANDLES_ABOVE  = 2
MOMENTUM_15M_PCT       = 0.15
MOMENTUM_1H_PCT        = 0.35
RSI_CONFIRMATION       = True
RSI_LONG_MIN           = 48.0
RSI_SHORT_MAX          = 52.0
MACD_CONFIRMATION      = True
OVERRIDE_VOLUME_SPIKE  = True
VOLUME_SPIKE_STRONG    = 200.0
MIN_ENTRY_COOLDOWN     = 15*60

# ---- Parametri VWAP+ ----
ROLLING_WINDOWS_D = [7, 30, 90, 365]
ROLLING_STDEV_MULT = 0.5
MIN_SCORE = 3
POC_BUFFER = 0.0005

STATE_PATH = ".vwap_bot_state.json"
DEFAULT_COOLDOWN_MIN = 60
DEFAULT_SCORE_BUMP = 1

# ================== UTIL ==========================
def load_dotenv_if_present():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

def minutes_to_interval(m: int) -> str:
    return {1:"1m",3:"3m",5:"5m",15:"15m",30:"30m",60:"1h",120:"2h",240:"4h"}.get(m, "15m")

def ensure_tz_utc(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df

def to_rome(df: pd.DataFrame) -> pd.DataFrame:
    try:
        return df.tz_convert(TZ_DISPLAY) if df.index.tz is not None else df
    except Exception:
        return df

def fmt_price(x: Optional[float]) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "-"
    return f"{x:.2f}" if x >= 1 else f"{x:.6f}"

def now_ts() -> int:
    return int(time.time())

def pct_change(a: float, b: float) -> Optional[float]:
    try:
        return (a - b) / b * 100.0 if b else None
    except Exception:
        return None

# ================== TELEGRAM ======================
def tg_token() -> Optional[str]:
    tok_env = os.getenv(ENV_TG_TOKEN, "").strip()
    if tok_env: return tok_env
    if TELEGRAM_BOT_TOKEN_FALLBACK: return TELEGRAM_BOT_TOKEN_FALLBACK.strip()
    return None

def tg_chat_id() -> Optional[str]:
    cid_env = os.getenv(ENV_TG_CHAT, "").strip()
    if cid_env: return cid_env
    if TELEGRAM_CHAT_ID_FALLBACK: return TELEGRAM_CHAT_ID_FALLBACK.strip()
    return None

def cmc_key() -> Optional[str]:
    key_env = os.getenv(ENV_CMC_KEY, "").strip()
    if key_env: return key_env
    if COINMARKETCAP_API_KEY_FALLBACK: return COINMARKETCAP_API_KEY_FALLBACK.strip()
    return None

def html_escape(s: str) -> str:
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def tg_send(html_text: str) -> bool:
    token, chat_id = tg_token(), tg_chat_id()
    if not token or not chat_id:
        logging.warning("Telegram: token/chat_id mancanti.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": html_text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.status_code == 200
    except Exception as e:
        logging.warning(f"Telegram send err: {e}")
        return False

def tg_photo(png_bytes: bytes, caption: str = "") -> bool:
    token, chat_id = tg_token(), tg_chat_id()
    if not token or not chat_id:
        logging.warning("Telegram: token/chat_id mancanti (photo).")
        return False
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    files = {"photo": ("chart.png", png_bytes, "image/png")}
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=data, files=files, timeout=20)
        return r.status_code == 200
    except Exception as e:
        logging.warning(f"Telegram photo err: {e}")
        return False

# ================== FETCHERS ======================
def fetch_binance_klines(symbol: str, interval_min: int, limit: int = 1000) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": minutes_to_interval(interval_min), "limit": limit}
    r = requests.get(url, params=params, timeout=20); r.raise_for_status()
    data = r.json()
    cols = ["open_time","open","high","low","close","volume","close_time","q","n","tb","tq","x"]
    df = pd.DataFrame(data, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    return df[["open","high","low","close","volume"]].astype(float)

def fetch_mexc_klines(symbol: str, interval_min: int, limit: int = 1000) -> pd.DataFrame:
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": minutes_to_interval(interval_min), "limit": limit}
    r = requests.get(url, params=params, timeout=20); r.raise_for_status()
    data = r.json()
    cols = ["open_time","open","high","low","close","volume","close_time","q","n","tb","tq","x"]
    df = pd.DataFrame(data, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    return df[["open","high","low","close","volume"]].astype(float)

def fetch_cmc_quote(symbols: List[str]) -> dict:
    key = cmc_key()
    if not key:
        return {}
    mapping = {"BTCUSDT":"BTC", "ETHUSDT":"ETH"}
    bases = sorted({mapping.get(s, s) for s in symbols})
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
    headers = {"X-CMC_PRO_API_KEY": key}
    params = {"symbol": ",".join(bases), "convert": "USD"}
    r = requests.get(url, headers=headers, params=params, timeout=20); r.raise_for_status()
    js = r.json().get("data", {})
    out = {}
    for base in bases:
        item = js.get(base, [{}])[0] if isinstance(js.get(base, {}), list) else js.get(base, {})
        q = (item or {}).get("quote", {}).get("USD", {})
        out[base] = {"price_usd": q.get("price"), "vol24_usd": q.get("volume_24h"), "percent_change_24h": q.get("percent_change_24h")}
    return out

# ================== AGGREGAZIONE ==================
def align_and_aggregate(dfs: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    parts=[]
    for ex, df in dfs.items():
        df = ensure_tz_utc(df)
        parts.append(df[["close","volume"]].rename(columns={"close":f"close_{ex}","volume":f"vol_{ex}"}))
    if not parts: return pd.DataFrame()
    out = pd.concat(parts, axis=1).sort_index()
    close_cols=[c for c in out.columns if c.startswith("close_")]
    vol_cols  =[c for c in out.columns if c.startswith("vol_")]
    out["close_ref"] = out[close_cols].mean(axis=1, skipna=True)
    out["vol_agg"]   = out[vol_cols].sum(axis=1, skipna=True)
    out["close"]     = out["close_ref"]
    return out[["close","close_ref","vol_agg"]]

# ================== INDICATORI VWAP+ ==============
def anchored_vwap(df: pd.DataFrame, anchor_freq: str) -> pd.DataFrame:
    if df.empty: return pd.DataFrame(index=df.index)
    tag={"D":"d","W":"w","M":"m","Q":"q","Y":"y"}[anchor_freq]
    g = df.groupby(pd.Grouper(freq=anchor_freq))
    num = g.apply(lambda x:(x["close_ref"]*x["vol_agg"]).cumsum()).reset_index(level=0, drop=True)
    den = g.apply(lambda x:(x["vol_agg"]).cumsum()).reset_index(level=0, drop=True).replace(0,np.nan)
    vwap = num/den
    ex2  = g.apply(lambda x:(x["vol_agg"]*(x["close_ref"]**2)).cumsum()).reset_index(level=0, drop=True)/den
    var  = (ex2 - vwap**2).clip(lower=0); stdev = np.sqrt(var)
    out = pd.DataFrame(index=df.index)
    out[f"vw_{tag}"]=vwap; out[f"vw_{tag}_u"]=vwap+stdev; out[f"vw_{tag}_l"]=vwap-stdev
    return out

def rolling_vwap(df: pd.DataFrame, window_bars: int, stdev_mult: float = 0.5) -> pd.DataFrame:
    if df.empty or window_bars<=1: return pd.DataFrame(index=df.index)
    price=df["close_ref"].to_numpy(); vol=df["vol_agg"].to_numpy()
    k=np.ones(window_bars,float)
    num=np.convolve(price*vol,k,mode="same"); den=np.convolve(vol,k,mode="same")
    rvwap=num/np.where(den==0,np.nan,den)
    ex2=np.convolve(vol*(price**2),k,mode="same")/np.where(den==0,np.nan,den)
    var=np.clip(ex2-rvwap**2,0,None); stdev=np.sqrt(var)
    out=pd.DataFrame(index=df.index)
    out["rvwap"]=rvwap; out["rvwap_u"]=rvwap+stdev*stdev_mult; out["rvwap_l"]=rvwap-stdev*stdev_mult
    return out

def previous_period_levels(df: pd.DataFrame, anchor_freq: str) -> pd.DataFrame:
    tag={"D":"d","W":"w","M":"m","Q":"q","Y":"y"}[anchor_freq]
    aw=anchored_vwap(df,anchor_freq); merged=df.join(aw,how="left")
    grp=merged.groupby(pd.Grouper(freq=anchor_freq))
    last=grp[[f"vw_{tag}",f"vw_{tag}_u",f"vw_{tag}_l"]].last().shift(1)
    prev=last.reindex(merged.index,method="ffill"); prev.columns=[f"prev_{tag}_poc",f"prev_{tag}_u",f"prev_{tag}_l"]
    return prev

def compute_slopes(series: pd.Series, lookback: int=5)->pd.Series:
    if series.isna().all(): return pd.Series(index=series.index,dtype=float)
    return (series-series.shift(lookback))/lookback

def build_feature_frame(df: pd.DataFrame, tf_minutes: int) -> pd.DataFrame:
    out=df.copy()
    for f in ["D","W","M","Q","Y"]: out=out.join(anchored_vwap(out,f),how="left")
    for f in ["D","W","M","Q","Y"]: out=out.join(previous_period_levels(out,f),how="left")
    bars_per_day=max(1,int(24*60//tf_minutes))
    for d in [7,30,90,365]:
        rv=rolling_vwap(out, d*bars_per_day, 0.5)
        out=out.join(rv.add_prefix(f"rv{d}_"))
    out["rv30_slope"]=compute_slopes(out["rv30_rvwap"]).fillna(0)
    out["vol_p70"]=out["vol_agg"].rolling(20,min_periods=5).quantile(0.7)
    out["above_week_vwap"]=out["close"]>out["vw_w"]
    out["above_rv7"]=out["close"]>out["rv7_rvwap"]
    poc=out["prev_w_poc"]
    out["reclaim_prev_week_poc"]=(out["close"]>poc*(1+POC_BUFFER)) & (out["close"].shift(1)<=poc*(1+POC_BUFFER))
    out["reject_prev_week_poc"] =(out["close"]<poc*(1-POC_BUFFER)) & (out["close"].shift(1)>=poc*(1-POC_BUFFER))
    out["cross_up_rv30_l"]=(out["close"].shift(1)<=out["rv30_rvwap_l"].shift(1)) & (out["close"]>out["rv30_rvwap_l"])
    out["cross_dn_rv30_u"]=(out["close"].shift(1)>=out["rv30_rvwap_u"].shift(1)) & (out["close"]<out["rv30_rvwap_u"])
    return out

# ================== INDICATORI LEGACY =============
def rsi(series: pd.Series, period: int=14)->pd.Series:
    d=series.diff()
    up=d.clip(lower=0).rolling(period).mean()
    dn=(-d.clip(upper=0)).rolling(period).mean()
    rs=up/dn.replace(0,np.nan)
    return 100-(100/(1+rs))

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast=series.ewm(span=fast, adjust=False).mean()
    ema_slow=series.ewm(span=slow, adjust=False).mean()
    line=ema_fast-ema_slow
    sig=line.ewm(span=signal, adjust=False).mean()
    hist=line-sig
    return line, sig, hist

def trend_label(series: pd.Series, lb:int=5)->str:
    if len(series)<lb+1: return "neutro"
    v=(series.iloc[-1]-series.iloc[-lb])/max(lb,1)
    if v>0: return "rialzo"
    if v<0: return "ribasso"
    return "neutro"

def volume_spike(series: pd.Series, look:int=20)->Tuple[str,float]:
    if len(series)<look+1: return ("",0.0)
    avg=series.iloc[-(look+1):-1].mean()
    cur=series.iloc[-1]
    pct=pct_change(cur, avg) if avg else 0.0
    if pct is None: pct=0.0
    if pct>=VOLUME_SPIKE_STRONG: return ("↑ forte", pct)
    if pct>=100: return ("↑", pct)
    if pct<=-50: return ("↓", pct)
    return ("", pct)

# ================== VWAP+ DECISION =================
def vwap_decide(row: pd.Series, cmc_ctx: Optional[dict])->Tuple[Optional[str],int,List[str]]:
    score=0; notes=[]
    if row.get("rv30_slope",0)>0: score+=1; notes.append("Trend RVWAP30 in salita")
    if row.get("above_week_vwap",False): score+=1; notes.append("Prezzo sopra VWAP settimanale")
    if row.get("above_rv7",False): score+=1; notes.append("Prezzo sopra RVWAP 7 giorni")
    if not math.isnan(row.get("vol_p70",math.nan)) and row.get("vol_agg",0)>row.get("vol_p70",0):
        score+=1; notes.append("Volume aggregato sopra 70° percentile")
    action=None
    if row.get("reclaim_prev_week_poc",False): action="BUY";  notes.append("Reclaim POC settimanale precedente")
    if row.get("reject_prev_week_poc",False):  action="SELL"; notes.append("Reject POC settimanale precedente")
    if action is None and row.get("cross_up_rv30_l",False): action="BUY";  notes.append("Rebound su RVWAP30 low")
    if action is None and row.get("cross_dn_rv30_u",False): action="SELL"; notes.append("Reject su RVWAP30 high")
    if cmc_ctx:
        chg=cmc_ctx.get("percent_change_24h")
        if action=="BUY" and chg and chg>0: score+=1; notes.append("CMC: 24h positiva")
        if action=="SELL" and chg and chg<0: score+=1; notes.append("CMC: 24h negativa")
    if action is None or score<MIN_SCORE: return None, score, notes
    return action, score, notes

def vwap_propose_risk(row: pd.Series, action:str)->Tuple[Optional[float],Optional[float],Optional[float]]:
    if action=="BUY":
        stop=float(np.nanmax([row.get("rv30_rvwap_l",np.nan), row.get("prev_w_l",np.nan)]))
        tp1=float(row.get("rv30_rvwap",np.nan)); tp2=float(row.get("rv30_rvwap_u",np.nan))
    else:
        stop=float(np.nanmin([row.get("rv30_rvwap_u",np.nan), row.get("prev_w_u",np.nan)]))
        tp1=float(row.get("rv30_rvwap",np.nan)); tp2=float(row.get("rv30_rvwap_l",np.nan))
    return (None if np.isnan(stop) else stop,
            None if np.isnan(tp1)  else tp1,
            None if np.isnan(tp2)  else tp2)

# ================== LEGACY ENGINE ==================
class PosState:
    def __init__(self):
        self.side=None; self.entry=None; self.sl=None; self.tp1=None; self.tp2=None
        self.hit_tp1=False; self.last_entry_ts=0.0

POS: Dict[str, PosState] = {}

def get_pos(symbol:str)->PosState:
    if symbol not in POS: POS[symbol]=PosState()
    return POS[symbol]

def make_chart_png(symbol:str, k15: pd.DataFrame, R: float, S: float, price: float)->bytes:
    fig, ax = plt.subplots(figsize=(8,4))
    ax.plot(k15.index, k15["close"], linewidth=1)
    ax.axhline(R, linestyle="--")
    ax.axhline(S, linestyle="--")
    ax.set_title(f"{symbol} — {BRAND}")
    ax.set_xlabel("Tempo"); ax.set_ylabel("Prezzo")
    ax.grid(True, linestyle=":")
    bio = io.BytesIO(); fig.tight_layout(); plt.savefig(bio, format="png", dpi=160); plt.close(fig)
    return bio.getvalue()

def legacy_engine(symbol:str, k15: pd.DataFrame, feat15: pd.DataFrame)->Optional[str]:
    if len(k15)<50: return None
    P = get_pos(symbol)
    closes15 = k15["close"].tolist()
    price = closes15[-1]

    res = float(feat15.get("rv30_rvwap_u", pd.Series([price*1.01])).iloc[-1])  # R
    sup = float(feat15.get("rv30_rvwap_l", pd.Series([price*0.99])).iloc[-1])  # S

    tr15 = trend_label(pd.Series(closes15), lb=5)
    tr30 = trend_label(pd.Series(closes15).rolling(2).mean().dropna(), lb=5)

    rsi15 = float(rsi(pd.Series(closes15),14).iloc[-1]) if len(closes15)>=20 else None
    macd_line, macd_sig, _ = macd(pd.Series(closes15))
    macd_ok_long  = macd_line.iloc[-1] > macd_sig.iloc[-1]
    macd_ok_short = macd_line.iloc[-1] < macd_sig.iloc[-1]

    sp_lbl, sp_pct = volume_spike(k15["volume"], look=20)

    # ---------------- condizioni di ingresso (dinamiche) ----------------
    soft_long  = price > res * (1.0 + SOFT_BREAKOUT_PCT/100.0)
    soft_short = price < sup * (1.0 - SOFT_BREAKOUT_PCT/100.0)

    above_count = sum(1 for c in closes15[-REQUIRE_CANDLES_ABOVE:] if c > res)
    below_count = sum(1 for c in closes15[-REQUIRE_CANDLES_ABOVE:] if c < sup)
    closes_ok_long  = (REQUIRE_CANDLES_ABOVE <= 1) or (above_count >= REQUIRE_CANDLES_ABOVE)
    closes_ok_short = (REQUIRE_CANDLES_ABOVE <= 1) or (below_count >= REQUIRE_CANDLES_ABOVE)

    m15 = pct_change(closes15[-1], closes15[-2]) if len(closes15) >= 2 else None
    m1h = pct_change(closes15[-1], closes15[-5]) if len(closes15) >= 5 else None

    momentum_long  = ((m15 is not None and m15 >= MOMENTUM_15M_PCT) or (m1h is not None and m1h >= MOMENTUM_1H_PCT))
    momentum_short = ((m15 is not None and m15 <= -MOMENTUM_15M_PCT) or (m1h is not None and m1h <= -MOMENTUM_1H_PCT))

    spike_override = OVERRIDE_VOLUME_SPIKE and (sp_lbl == "↑ forte" or sp_pct >= VOLUME_SPIKE_STRONG)

    base_long  = ( (price > res) or (soft_long and closes_ok_long) or momentum_long or spike_override ) and tr15=="rialzo" and tr30 in ("rialzo","neutro")
    base_short = ( (price < sup) or (soft_short and closes_ok_short) or momentum_short or spike_override ) and tr15=="ribasso" and tr30 in ("ribasso","neutro")

    can_long, can_short = base_long, base_short
    if RSI_CONFIRMATION and rsi15 is not None:
        can_long  = can_long  and rsi15 >= RSI_LONG_MIN
        can_short = can_short and rsi15 <= RSI_SHORT_MAX
    if MACD_CONFIRMATION:
        can_long  = can_long  and macd_ok_long
        can_short = can_short and macd_ok_short

    try:
        print(f"[{symbol}] price={price:.2f} R={res:.2f} S={sup:.2f} "
              f"softL={soft_long} closeOKL={closes_ok_long} momL={momentum_long} "
              f"softS={soft_short} closeOKS={closes_ok_short} momS={momentum_short} "
              f"spike={spike_override} canL={can_long} canS={can_short}")
    except Exception:
        pass

    eL, sL = res, sup
    eS, sS = sup, res
    rv_mid = float(feat15.get("rv30_rvwap", pd.Series([price])).iloc[-1])
    rv_up  = float(feat15.get("rv30_rvwap_u", pd.Series([price*1.01])).iloc[-1])
    rv_lo  = float(feat15.get("rv30_rvwap_l", pd.Series([price*0.99])).iloc[-1])
    t1L, t2L = rv_mid, rv_up
    t1S, t2S = rv_mid, rv_lo

    def msg_entry(sym, side, entry, stop, tp1, tp2, price, rsi_val, macd_ok, lev):
        macd_txt = "OK" if macd_ok else "N/D"
        lev_txt = lev if lev else "-"
        return (f"<b>{html_escape(LOGO_PREFIX)}</b> <b>{html_escape(sym)}</b> • {BRAND}\n"
                f"<b>ENTRY {side.upper()}</b> @ <b>{fmt_price(entry)}</b>  (last {fmt_price(price)})\n"
                f"STOP <b>{fmt_price(stop)}</b> • TP1 <b>{fmt_price(tp1)}</b> • TP2 <b>{fmt_price(tp2)}</b>\n"
                f"RSI15: <b>{'-' if rsi_val is None else f'{rsi_val:.1f}'}</b> • MACD: <b>{macd_txt}</b> • VolSpike: <b>{sp_lbl or '-'}</b>\n"
                f"Livello R/S: <b>{fmt_price(res)}</b> / <b>{fmt_price(sup)}</b> • Lev: {html_escape(str(lev_txt))}")

    lev = "std"
    nowt = time.time()
    if P.side is None:
        if can_long and nowt - P.last_entry_ts > MIN_ENTRY_COOLDOWN:
            P.side="long"; P.entry=eL; P.sl=sL; P.tp1=t1L; P.tp2=t2L; P.hit_tp1=False; P.last_entry_ts=nowt
            tg_send(msg_entry(symbol,"long",eL,sL,t1L,t2L,price,rsi15, macd_ok_long, lev))
            try:
                img=make_chart_png(symbol,k15,res,sup,price)
                tg_photo(img, caption=f"{html_escape(LOGO_PREFIX)} {html_escape(symbol)} — <b>LONG setup</b>")
            except Exception: pass
            return "LONG"
        elif can_short and nowt - P.last_entry_ts > MIN_ENTRY_COOLDOWN:
            P.side="short"; P.entry=eS; P.sl=sS; P.tp1=t1S; P.tp2=t2S; P.hit_tp1=False; P.last_entry_ts=nowt
            tg_send(msg_entry(symbol,"short",eS,sS,price,rsi15, macd_ok_short, lev))
            try:
                img=make_chart_png(symbol,k15,res,sup,price)
                tg_photo(img, caption=f"{html_escape(LOGO_PREFIX)} {html_escape(symbol)} — <b>SHORT setup</b>")
            except Exception: pass
            return "SHORT"
    return None

# ================== VWAP+ SIGNALS =================
def vwap_generate_signals(df_feat: pd.DataFrame, market: str, tf_label: str, cmc_ctx: Optional[dict]) -> List[dict]:
    out=[]
    for ts, row in df_feat.iterrows():
        action, score, notes = vwap_decide(row, cmc_ctx)
        if action is None: continue
        stop, tp1, tp2 = vwap_propose_risk(row, action)
        out.append({
            "ts": ts.isoformat(), "market": market, "timeframe": tf_label,
            "signal": action, "score": int(score), "price": float(row["close"]),
            "levels": {
                "rvwap30": float(row.get("rv30_rvwap", np.nan)),
                "rvwap30_upper": float(row.get("rv30_rvwap_u", np.nan)),
                "rvwap30_lower": float(row.get("rv30_rvwap_l", np.nan)),
                "week_vwap": float(row.get("vw_w", np.nan)),
                "prev_week_poc": float(row.get("prev_w_poc", np.nan)),
                "prev_day_poc": float(row.get("prev_d_poc", np.nan)),
                "prev_month_poc": float(row.get("prev_m_poc", np.nan)),
                "prev_quarter_poc": float(row.get("prev_q_poc", np.nan)),
                "prev_year_poc": float(row.get("prev_y_poc", np.nan)),
            },
            "risk": {"stop": stop, "tp1": tp1, "tp2": tp2},
            "notes": notes
        })
    return out

def alerts_to_html(sig: dict, cmc_ctx: Optional[dict]=None, extra_reason:str="")->str:
    lv=sig["levels"]; rk=sig["risk"]
    note=" | ".join(sig["notes"]) if sig["notes"] else "-"
    rows=[]
    rows.append(f"<b>{html_escape(LOGO_PREFIX)}</b>  <b>{html_escape(sig['market'])}</b> • TF <b>{html_escape(sig['timeframe'])}</b> • {html_escape(BRAND)}")
    rows.append(f"<b>Segnale:</b> <b>{html_escape(sig['signal'])}</b> (score <b>{sig['score']}</b>)  @ <b>{fmt_price(sig['price'])}</b>")
    rows.append(f"RVWAP30: base <b>{fmt_price(lv['rvwap30'])}</b> • sup <b>{fmt_price(lv['rvwap30_upper'])}</b> • inf <b>{fmt_price(lv['rvwap30_lower'])}</b>")
    rows.append(f"VWAP sett.: <b>{fmt_price(lv['week_vwap'])}</b> • POC W-1: <b>{fmt_price(lv['prev_week_poc'])}</b>")
    rows.append(f"POC D/M/Q/Y: <b>{fmt_price(lv['prev_day_poc'])}</b> / <b>{fmt_price(lv['prev_month_poc'])}</b> / <b>{fmt_price(lv['prev_quarter_poc'])}</b> / <b>{fmt_price(lv['prev_year_poc'])}</b>")
    rows.append(f"Rischio — STOP: <b>{fmt_price(rk['stop'])}</b> • TP1: <b>{fmt_price(rk['tp1'])}</b> • TP2: <b>{fmt_price(rk['tp2'])}</b>")
    if cmc_ctx:
        chg=cmc_ctx.get("percent_change_24h"); v24=cmc_ctx.get("vol24_usd")
        rows.append(f"CoinMarketCap: Var 24h <b>{(chg if chg is not None else 0):+.2f}%</b> • Vol 24h <b>{(v24 if v24 else 0):,.0f}</b> USD".replace(",", "."))
    rows.append(f"Motivazioni: {html_escape(note)}")
    if extra_reason: rows.append(f"Nota debounce: {html_escape(extra_reason)}")
    return "\n".join(rows)

# ================== DEBOUNCE ======================
def load_state(path: str = STATE_PATH) -> dict:
    if not os.path.exists(path): return {}
    try:
        with open(path,"r",encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def save_state(state: dict, path: str = STATE_PATH)->None:
    try:
        with open(path,"w",encoding="utf-8") as f: json.dump(state,f,indent=2)
    except Exception as e:
        logging.warning(f"save_state err: {e}")

def state_key(symbol:str, tf:str)->str: return f"{symbol}:{tf}"

def should_emit(last_sig: Optional[dict], new_sig: dict, cooldown_min:int, score_bump:int)->Tuple[bool,str]:
    if last_sig is None: return True, "Primo segnale per coppia/TF"
    last_action=last_sig.get("signal"); last_score=last_sig.get("score",0)
    last_stop=last_sig.get("risk",{}).get("stop"); last_ts=last_sig.get("_saved_at",0)
    new_action=new_sig.get("signal"); new_score=new_sig.get("score",0); new_price=new_sig.get("price")
    if new_action and last_action and new_action!=last_action:
        return True, f"Direzione cambiata: {last_action} → {new_action}"
    if last_action=="BUY" and last_stop is not None and new_price is not None and new_price<=last_stop:
        return True, "Invalidazione BUY precedente (≤ STOP)"
    if last_action=="SELL" and last_stop is not None and new_price is not None and new_price>=last_stop:
        return True, "Invalidazione SELL precedente (≥ STOP)"
    if last_ts:
        elapsed=(now_ts()-last_ts)/60.0
        if elapsed>=cooldown_min: return True, f"Cooldown trascorso: {elapsed:.0f} ≥ {cooldown_min} min"
    if (new_score-last_score)>=score_bump:
        return True, f"Score migliorato: {last_score} → {new_score} (≥ +{score_bump})"
    return False, "Debounce attivo"

# ================== ORCHESTRAZIONE =================
def run_once_for_symbol(symbol: str, tfs: List[int]) -> dict:
    results={}
    base="BTC" if symbol.upper().startswith("BTC") else "ETH"
    cmc_all=fetch_cmc_quote([symbol]); cmc_ctx=cmc_all.get(base) if cmc_all else None
    for tf in tfs:
        try: b=fetch_binance_klines(symbol,tf,1000)
        except Exception as e: logging.warning(f"Binance err {symbol} {tf}m: {e}"); b=pd.DataFrame()
        try: m=fetch_mexc_klines(symbol,tf,1000)
        except Exception as e: logging.warning(f"MEXC err {symbol} {tf}m: {e}"); m=pd.DataFrame()
        agg=align_and_aggregate({"BINANCE":b,"MEXC":m})
        if agg.empty: results[str(tf)]=[]; continue
        feat=build_feature_frame(agg, tf); feat=to_rome(feat)
        mkt=f"{symbol.replace('USDT','')}/USDT"
        sigs=vwap_generate_signals(feat, market=mkt, tf_label=f"{tf}m", cmc_ctx=cmc_ctx)
        results[str(tf)]=sigs
        if tf==LEGACY_TF_MIN:
            legacy_engine(symbol, to_rome(b), feat)
    return results

def run_all_markets(symbols: List[str], tfs: List[int])->dict:
    return {sym: run_once_for_symbol(sym,tfs) for sym in symbols}

# ================== PIPELINE SEND ==================
def send_alerts(symbols: List[str],
                tfs: List[int],
                json_mode: bool,
                cooldown_min: int,
                score_bump: int,
                only_dir: Optional[str],
                dry_run: bool,
                do_push: bool) -> bool:
    state=load_state(STATE_PATH)
    cmc_ctx_all=fetch_cmc_quote(symbols)
    full=run_all_markets(symbols,tfs)

    emitted=False; outputs=[]
    for sym, tf_map in full.items():
        base = "BTC" if sym.upper().startswith("BTC") else "ETH"
        cmc_ctx = cmc_ctx_all.get(base) if cmc_ctx_all else None
        for tf, sigs in tf_map.items():
            if not sigs: continue
            last=sigs[-1]
            if only_dir and last["signal"]!=only_dir.upper(): continue
            k=state_key(sym,str(tf)); last_saved=state.get(k)
            emit, reason = should_emit(last_saved, last, cooldown_min, score_bump)
            if not emit: continue
            last["_saved_at"]=now_ts(); state[k]=last
            if json_mode:
                outputs.append(json.dumps(last, ensure_ascii=False))
            else:
                msg=alerts_to_html(last, cmc_ctx, extra_reason=reason); outputs.append(msg)
                if do_push and not dry_run: tg_send(msg)
            emitted=True
    save_state(state, STATE_PATH)
    print("Nessun nuovo alert (debounce)." if not emitted else "\n\n".join(outputs))
    return emitted

# ================== MAIN / LOOP ===================
def main():
    import argparse
    load_dotenv_if_present()
    parser=argparse.ArgumentParser(description=f"{BRAND} — VWAP+ + Legacy Breakout • Telegram")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--tf", nargs="+", type=int, default=TIMEFRAMES_MIN)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--cooldown-min", type=int, default=DEFAULT_COOLDOWN_MIN)
    parser.add_argument("--score-bump", type=int, default=DEFAULT_SCORE_BUMP)
    parser.add_argument("--only-dir", type=str, choices=["BUY","SELL"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--loop-seconds", type=int)
    args=parser.parse_args()

    if args.verbose: logging.getLogger().setLevel(logging.INFO)

    if not args.loop_seconds:
        send_alerts(args.symbols,args.tf,args.json,args.cooldown_min,args.score_bump,args.only_dir,args.dry_run,args.push)
    else:
        interval=max(30,args.loop_seconds); backoff=interval
        while True:
            try:
                send_alerts(args.symbols,args.tf,args.json,args.cooldown_min,args.score_bump,args.only_dir,args.dry_run,args.push)
                backoff=interval
            except Exception as e:
                logging.exception(f"Errore run: {e}")
                backoff=min(backoff*2,3600)
            time.sleep(backoff)

if __name__=="__main__":
    main()
