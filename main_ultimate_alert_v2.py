# ---------- BTC/ETH ALERT BOT (SNELLO & NO-SPAM) ----------
import time, hashlib, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# === CONFIG ===
TOKEN   = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"
KLINE_URL = "https://api.mexc.com/api/v3/klines?symbol={s}USDT&interval=15m&limit=120"

TP_PCT = 1.0      # target %
SL_PCT = 0.3      # stop %
VOL_MULT = 1.2    # vol15m >= VOL_MULT * media 12h
REPORT_MIN_GAP = 12*60  # tra due report uguali, al minimo 12 min
WEAK_COOLDOWN   = 10*60 # min intervallo tra weak alert
STRONG_COOLDOWN = 15*60 # min intervallo tra strong alert

# === STATO ===
S = {
  "BTC": {"strong_dir":None, "weak_ts":0.0, "strong_ts":0.0, "trade":None},
  "ETH": {"strong_dir":None, "weak_ts":0.0, "strong_ts":0.0, "trade":None},
}
LAST_REPORT_HASH = None
LAST_REPORT_TS   = 0.0
STARTUP_SENT = False

# === UTILITY ===
def tg(msg:str):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                       data={"chat_id":CHAT_ID,"text":msg},timeout=8)
    except: pass

def klines(sym):
    try:
        r=requests.get(KLINE_URL.format(s=sym),headers={"User-Agent":"ok"},timeout=12)
        r.raise_for_status(); return r.json()
    except: return None

def ema_series(x, p):
    k=2/(p+1); out=[]; e=x[0]
    for v in x: e=v*k+e*(1-k); out.append(e)
    return out

def atr(cl, hi, lo, p=20):
    if len(cl)<2: return 0.0
    trs=[max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1])) for i in range(1,len(cl))]
    return ema_series(trs,p)[-1] if len(trs)>=p else trs[-1]

def macd_hist(cl):
    e12=ema_series(cl,12); e26=ema_series(cl,26)
    mac=[a-b for a,b in zip(e12[-len(e26):],e26)]
    sig=ema_series(mac,9)
    return mac[-1]-sig[-1]

def next_half_hour():
    now = datetime.now(tz=ZoneInfo("UTC")).replace(second=0,microsecond=0)
    add = 30-(now.minute%30)
    if add==0: add=30
    return (now+timedelta(minutes=add)).timestamp()

# === ANALISI ===
def analyze(sym):
    d = klines(sym)
    if not d or len(d)<60: return None
    op=[float(c[1]) for c in d]
    hi=[float(c[2]) for c in d]
    lo=[float(c[3]) for c in d]
    cl=[float(c[4]) for c in d]
    q =[float(c[5]) for c in d]
    usdt=[cl[i]*q[i] for i in range(len(cl))]

    vol15 = usdt[-1]
    avg12 = sum(usdt[-48:])/48
    ema20 = ema_series(cl[-60:],20); ema60 = ema_series(cl[-60:],60)
    ema20_prev, ema20_now = ema20[-2], ema20[-1]
    atr20 = atr(cl[-60:],hi[-60:],lo[-60:],20)
    hist  = macd_hist(cl[-120:])
    swing_hi=max(hi[-96:]); swing_lo=min(lo[-96:])
    breakout = sorted({round(swing_hi,2), round(ema20_now+atr20,2)})
    breakdown= sorted({round(swing_lo,2), round(ema20_now-atr20,2)}, reverse=True)

    return {
      "price":cl[-1], "open":op[-1], "vol15":vol15, "avg12":avg12,
      "ema20":ema20_now,"ema20p":ema20_prev,"ema60":ema60[-1],
      "bull":cl[-1]>op[-1], "bear":cl[-1]<op[-1], "hist":hist,
      "levels":{"bo":breakout,"bd":breakdown}
    }

# === TRADE ===
def open_trade(sym, side, entry):
    if side=="LONG": tp=entry*(1+TP_PCT/100); sl=entry*(1-SL_PCT/100)
    else:            tp=entry*(1-TP_PCT/100); sl=entry*(1+SL_PCT/100)
    S[sym]["trade"]={"side":side,"entry":entry,"tp":tp,"sl":sl}
    tg(f"🔥 SEGNALE FORTISSIMO {side} {sym}\nEntra: {entry:.2f} | Target: {tp:.2f} | Stop: {sl:.2f}")

def monitor(sym, price):
    t=S[sym]["trade"]
    if not t: return
    if t["side"]=="LONG":
        if price>=t["tp"]: tg(f"✅ TP LONG {sym} a {t['tp']:.2f}"); S[sym]["trade"]=None
        elif price<=t["sl"]: tg(f"❌ STOP LONG {sym} a {t['sl']:.2f}"); S[sym]["trade"]=None
    else:
        if price<=t["tp"]: tg(f"✅ TP SHORT {sym} a {t['tp']:.2f}"); S[sym]["trade"]=None
        elif price>=t["sl"]: tg(f"❌ STOP SHORT {sym} a {t['sl']:.2f}"); S[sym]["trade"]=None

# === SIGNALS ===
def signal(sym, a):
    p=a["price"]; v=a["vol15"]; avg=a["avg12"]
    e20=a["ema20"]; e20p=a["ema20p"]; e60=a["ema60"]; hist=a["hist"]
    bull=a["bull"]; bear=a["bear"]; lv=a["levels"]
    vol_ok = v >= VOL_MULT*avg

    # LONG
    for L in lv["bo"]:
        if p>=L and e20>e60 and e20>e20p and bull and hist>0 and p>=e20:
            now=time.time()
            if vol_ok and now-S[sym]["strong_ts"]>=STRONG_COOLDOWN and S[sym]["strong_dir"]!="LONG":
                open_trade(sym,"LONG",p); S[sym]["strong_dir"]="LONG"; S[sym]["strong_ts"]=now
            elif (not vol_ok) and now-S[sym]["weak_ts"]>=WEAK_COOLDOWN:
                tg(f"⚠️ Breakout debole {sym} | {p:.2f}$ | Vol15m {v/1e6:.1f}M"); S[sym]["weak_ts"]=now
            break

    # SHORT
    for L in lv["bd"]:
        if p<=L and e20<e60 and e20<e20p and bear and hist<0 and p<=e20:
            now=time.time()
            if vol_ok and now-S[sym]["strong_ts"]>=STRONG_COOLDOWN and S[sym]["strong_dir"]!="SHORT":
                open_trade(sym,"SHORT",p); S[sym]["strong_dir"]="SHORT"; S[sym]["strong_ts"]=now
            elif (not vol_ok) and now-S[sym]["weak_ts"]>=WEAK_COOLDOWN:
                tg(f"⚠️ Breakdown debole {sym} | {p:.2f}$ | Vol15m {v/1e6:.1f}M"); S[sym]["weak_ts"]=now
            break

    # reset direzione se prezzo torna tra i due livelli
    if max(lv["bd"]) < p < min(lv["bo"]): S[sym]["strong_dir"]=None

# === REPORT ===
def trend_emoji(e20,e60): return "🟢" if e20>e60 else ("🔴" if e20<e60 else "⚪")

def report_line(sym, a):
    return f"{trend_emoji(a['ema20'],a['ema60'])} {sym}: {a['price']:.2f}$ | EMA20:{a['ema20']:.2f} | EMA60:{a['ema60']:.2f} | Vol15m:{a['vol15']/1e6:.1f}M (avg:{a['avg12']/1e6:.1f}M)"

def build_report():
    A = {s: analyze(s) for s in ["BTC","ETH"]}
    if not A["BTC"] or not A["ETH"]: return None
    parts = [report_line("BTC",A["BTC"]), report_line("ETH",A["ETH"])]
    b=trend_emoji(A["BTC"]["ema20"],A["BTC"]["ema60"])
    e=trend_emoji(A["ETH"]["ema20"],A["ETH"]["ema60"])
    sug = "Preferenza LONG ✅" if b=="🟢" and e=="🟢" else "Preferenza SHORT ❌" if b=="🔴" and e=="🔴" else "Trend misto – Attendere conferma ⚠️"
    it = datetime.now(tz=ZoneInfo("Europe/Rome")).strftime("%d/%m %H:%M")
    utc= datetime.now(tz=ZoneInfo("UTC")).strftime("%d/%m %H:%M")
    text = f"🕒 Report {it} (Italia) | {utc} UTC\n\n" + "\n".join(parts) + f"\n\nSuggerimento: {sug}"
    return text, A

def send_report_no_dup():
    global LAST_REPORT_HASH, LAST_REPORT_TS
    build = build_report()
    if not build: return
    text, A = build
    h = hashlib.sha1(text.encode()).hexdigest()
    now = time.time()
    if h==LAST_REPORT_HASH and now-LAST_REPORT_TS<REPORT_MIN_GAP:
        return
    tg(text)
    LAST_REPORT_HASH, LAST_REPORT_TS = h, now

# === MAIN ===
if not STARTUP_SENT:
    tg("✅ Bot PRO attivo – Segnali Forti con TP/SL dinamici (Apple Watch ready)")
    STARTUP_SENT = True

next_report_ts = None
report_immediate = True

def schedule_next():
    return next_half_hour()

next_report_ts = schedule_next()

while True:
    try:
        for s in ["BTC","ETH"]:
            a=analyze(s)
            if not a: continue
            signal(s,a)
            monitor(s,a["price"])
        if report_immediate or time.time()>=next_report_ts:
            report_immediate=False
            send_report_no_dup()
            next_report_ts = schedule_next()
        time.sleep(5)
    except Exception:
        time.sleep(10)
