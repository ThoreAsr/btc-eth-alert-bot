# ================= BTC/ETH ULTIMATE BOT (CLEAN) =================
# Dipendenze: requests
import time, hashlib, requests
from datetime import datetime, timedelta

# --- Fuso Italia con fallback se zoneinfo non disponibile ---
try:
    from zoneinfo import ZoneInfo
    Z_ITALY = ZoneInfo("Europe/Rome")
    Z_UTC   = ZoneInfo("UTC")
    def now_it():  return datetime.now(Z_ITALY)
    def now_utc(): return datetime.now(Z_UTC)
except Exception:
    def now_it():  return datetime.utcnow() + timedelta(hours=2)  # fallback estivo
    def now_utc(): return datetime.utcnow()

# ----------------------- CONFIGURAZIONE ------------------------
TOKEN   = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"

# Dati da MEXC 15m
KLINE_URL = "https://api.mexc.com/api/v3/klines?symbol={s}USDT&interval=15m&limit=120"

# Filtri segnali forti
VOL_MULT       = 1.30     # vol15m >= VOL_MULT * media vol (12h)
TP_PCT         = 1.00     # target %
SL_PCT         = 0.30     # stop  %
STRONG_COOLD   = 15*60    # cooldown per simbolo/direzione
REPORT_MIN_GAP = 14*60    # minimo tra due report identici
POLL_SLEEP     = 5        # pausa loop
# ---------------------------------------------------------------

# Stato runtime (in memoria)
STATE = {
    "BTC": {"last_hash": None, "cool_ts": 0.0, "dir": None, "trade": None},
    "ETH": {"last_hash": None, "cool_ts": 0.0, "dir": None, "trade": None},
}
LAST_REPORT_HASH = None
LAST_REPORT_TS   = 0.0
STARTUP_SENT     = False

# ------------------------- TELEGRAM ----------------------------
def tg(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=8
        )
    except Exception:
        pass

# --------------------------- DATI ------------------------------
def klines(sym):
    try:
        r = requests.get(
            KLINE_URL.format(s=sym),
            headers={"User-Agent": "ok"},
            timeout=12
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def ema_series(x, p):
    k = 2/(p+1)
    out=[]; e=x[0]
    for v in x:
        e = v*k + e*(1-k)
        out.append(e)
    return out

def atr(cl, hi, lo, p=20):
    if len(cl) < 2: return 0.0
    trs=[]
    for i in range(1,len(cl)):
        trs.append(max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1])))
    if len(trs) < p: return trs[-1]
    return ema_series(trs, p)[-1]

def macd_hist(cl):
    e12=ema_series(cl,12)
    e26=ema_series(cl,26)
    mac=[a-b for a,b in zip(e12[-len(e26):], e26)]
    sig=ema_series(mac,9)
    return mac[-1]-sig[-1]

def analyze(sym):
    d = klines(sym)
    if not d or len(d) < 60: return None

    op=[float(c[1]) for c in d]
    hi=[float(c[2]) for c in d]
    lo=[float(c[3]) for c in d]
    cl=[float(c[4]) for c in d]
    q =[float(c[5]) for c in d]
    usdt=[cl[i]*q[i] for i in range(len(cl))]

    ema20 = ema_series(cl[-60:], 20)
    ema60 = ema_series(cl[-60:], 60)
    atr20 = atr(cl[-60:], hi[-60:], lo[-60:], 20)
    hist  = macd_hist(cl[-120:])

    swing_hi = max(hi[-96:])  # 24h
    swing_lo = min(lo[-96:])
    bo = sorted({round(swing_hi,2), round(ema20[-1] + atr20,2)})
    bd = sorted({round(swing_lo,2), round(ema20[-1] - atr20,2)}, reverse=True)

    vol15 = usdt[-1]
    avg12 = sum(usdt[-48:])/48  # 12h

    return {
        "price": cl[-1], "open": op[-1],
        "ema20": ema20[-1], "ema20p": ema20[-2], "ema60": ema60[-1],
        "hist":  hist,
        "vol15": vol15, "avg12": avg12,
        "bull":  cl[-1] > op[-1],
        "bear":  cl[-1] < op[-1],
        "levels": {"bo": bo, "bd": bd}
    }

# --------------------- TRADE MANAGEMENT -----------------------
def open_trade(sym, side, entry):
    if side=="LONG":
        tp = entry*(1+TP_PCT/100); sl = entry*(1-SL_PCT/100)
    else:
        tp = entry*(1-TP_PCT/100); sl = entry*(1+SL_PCT/100)
    STATE[sym]["trade"] = {"side":side, "entry":entry, "tp":tp, "sl":sl}
    tg(f"🔥 SEGNALE FORTISSIMO {side} {sym}\nEntra: {entry:.2f} | Target: {tp:.2f} | Stop: {sl:.2f}")

def monitor(sym, price):
    t = STATE[sym]["trade"]
    if not t: return
    if t["side"]=="LONG":
        if price >= t["tp"]: tg(f"✅ TP LONG {sym} a {t['tp']:.2f}"); STATE[sym]["trade"]=None
        elif price <= t["sl"]: tg(f"❌ STOP LONG {sym} a {t['sl']:.2f}"); STATE[sym]["trade"]=None
    else:
        if price <= t["tp"]: tg(f"✅ TP SHORT {sym} a {t['tp']:.2f}"); STATE[sym]["trade"]=None
        elif price >= t["sl"]: tg(f"❌ STOP SHORT {sym} a {t['sl']:.2f}"); STATE[sym]["trade"]=None

# ----------------------- SIGNALI FORTI ------------------------
def strong_signal(sym, a):
    p=a["price"]; e20=a["ema20"]; e20p=a["ema20p"]; e60=a["ema60"]
    hist=a["hist"]; bull=a["bull"]; bear=a["bear"]
    v=a["vol15"]; avg=a["avg12"]; lv=a["levels"]
    vol_ok = v >= VOL_MULT*avg

    # LONG forte
    for L in lv["bo"]:
        if p>=L and e20>e60 and e20>e20p and bull and hist>0 and p>=e20 and vol_ok:
            return "LONG"
        break
    # SHORT forte
    for L in lv["bd"]:
        if p<=L and e20<e60 and e20<e20p and bear and hist<0 and p<=e20 and vol_ok:
            return "SHORT"
        break
    return None

def maybe_signal(sym, a):
    side = strong_signal(sym, a)
    if not side:
        # reset in zona neutra
        p=a["price"]; lv=a["levels"]
        if max(lv["bd"]) < p < min(lv["bo"]): STATE[sym]["dir"]=None
        return
    # anti-duplicato + cooldown
    now=time.time()
    if STATE[sym]["dir"]==side and (now-STATE[sym]["cool_ts"])<STRONG_COOLD:
        return
    h = hashlib.sha1(f"{sym}|{side}|{a['price']:.2f}".encode()).hexdigest()
    if h==STATE[sym]["last_hash"] and (now-STATE[sym]["cool_ts"])<STRONG_COOLD:
        return
    open_trade(sym, side, a["price"])
    STATE[sym]["dir"]=side; STATE[sym]["cool_ts"]=now; STATE[sym]["last_hash"]=h

# -------------------------- REPORT ----------------------------
def trend_emoji(e20,e60): return "🟢" if e20>e60 else ("🔴" if e20<e60 else "⚪")

def report_line(sym, a):
    return (f"{trend_emoji(a['ema20'],a['ema60'])} {sym}: {a['price']:.2f}$ | "
            f"EMA20:{a['ema20']:.2f} | EMA60:{a['ema60']:.2f} | "
            f"Vol15m:{a['vol15']/1e6:.1f}M (avg:{a['avg12']/1e6:.1f}M)")

def build_report():
    A = {s: analyze(s) for s in ["BTC","ETH"]}
    if not A["BTC"] or not A["ETH"]: return None, None
    it  = now_it().strftime("%d/%m %H:%M")
    utc = now_utc().strftime("%d/%m %H:%M")
    text = (f"🕒 Report {it} (Italia) | {utc} UTC\n\n"
            f"{report_line('BTC',A['BTC'])}\n"
            f"{report_line('ETH',A['ETH'])}")
    b = trend_emoji(A["BTC"]["ema20"], A["BTC"]["ema60"])
    e = trend_emoji(A["ETH"]["ema20"], A["ETH"]["ema60"])
    if   b=="🟢" and e=="🟢": sug="Preferenza LONG ✅"
    elif b=="🔴" and e=="🔴": sug="Preferenza SHORT ❌"
    else:                    sug="Trend misto – Attendere conferma ⚠️"
    text += f"\n\nSuggerimento: {sug}"
    return text, A

def send_report_no_dup():
    global LAST_REPORT_HASH, LAST_REPORT_TS
    text, A = build_report()
    if not text: return
    h = hashlib.sha1(text.encode()).hexdigest()
    now=time.time()
    if h==LAST_REPORT_HASH and (now-LAST_REPORT_TS)<REPORT_MIN_GAP:
        return
    tg(text)
    LAST_REPORT_HASH=h; LAST_REPORT_TS=now
    # monitora TP/SL subito dopo
    for s in ["BTC","ETH"]:
        monitor(s, A[s]["price"])

# ------------------------ SCHEDULER ---------------------------
def next_half_hour_ts():
    t = now_utc().replace(second=0, microsecond=0)
    add = 30 - (t.minute % 30)
    if add==0: add=30
    return (t + timedelta(minutes=add)).timestamp()

# --------------------------- MAIN -----------------------------
if not STARTUP_SENT:
    tg("✅ Bot PRO attivo – Segnali Forti con TP/SL dinamici (Apple Watch ready)")
    STARTUP_SENT=True

next_report = next_half_hour_ts()

while True:
    try:
        for s in ["BTC","ETH"]:
            a = analyze(s)
            if not a: continue
            maybe_signal(s, a)
            monitor(s, a["price"])

        if time.time() >= next_report:
            send_report_no_dup()
            next_report = next_half_hour_ts()

        time.sleep(POLL_SLEEP)

    except Exception:
        time.sleep(10)
