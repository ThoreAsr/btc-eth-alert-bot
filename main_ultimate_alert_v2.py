# ================ BTC/ETH VOLUMES-ONLY BOT (Italy time, clean) ================
# Dipendenze: requests
import time, hashlib, requests
from datetime import datetime, timedelta

# ---- Orario Italia (con fallback se zoneinfo non disponibile) ----
try:
    from zoneinfo import ZoneInfo
    Z_ITALY = ZoneInfo("Europe/Rome")
    def now_it():  return datetime.now(Z_ITALY)
except Exception:
    def now_it():  return datetime.utcnow() + timedelta(hours=2)  # fallback estivo

# --------------------------- CONFIG --------------------------------
TOKEN   = "7743774612:AAFPCrhztElZoKqBuQ3HV8aPTfIianV8XzA"
CHAT_ID = "-1002181919588"

KLINE_URL = "https://api.mexc.com/api/v3/klines?symbol={s}USDT&interval=15m&limit=120"

# Volumi & trade
VOL_MULT       = 1.30   # vol15m deve essere >= 1.30 * media 12h
TP_PCT         = 1.00   # target %
SL_PCT         = 0.30   # stop   %

# Anti-spam
STRONG_COOLD   = 15*60  # 15 minuti tra due segnali forti dello stesso tipo
REPORT_MIN_GAP = 14*60  # non reinviare lo stesso report identico entro 14 min
POLL_SLEEP     = 5      # secondi tra un ciclo e l'altro

# --------------------------- STATO ---------------------------------
STATE = {
    "BTC": {"last_sig_hash": None, "cool_ts": 0.0, "dir": None, "trade": None},
    "ETH": {"last_sig_hash": None, "cool_ts": 0.0, "dir": None, "trade": None},
}
LAST_REPORT_HASH = None
LAST_REPORT_TS   = 0.0
STARTUP_SENT     = False

# ------------------------- TELEGRAM --------------------------------
def tg(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=8
        )
    except Exception:
        pass

# --------------------------- DATI ----------------------------------
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

def analyze(sym):
    """
    Ritorna:
      price, open, vol15m, avg12h, setup ('LONG'/'SHORT'/None) basato su volumi + trend-safety,
      e dati minimi per TP/SL
    Nota: internamente uso EMA e candela per evitare falsi segnali,
          ma nel report mostro SOLO i volumi come richiesto.
    """
    d = klines(sym)
    if not d or len(d) < 60: 
        return None

    op=[float(c[1]) for c in d]
    cl=[float(c[4]) for c in d]
    q =[float(c[5]) for c in d]
    usdt=[cl[i]*q[i] for i in range(len(cl))]

    # Volumi
    vol15 = usdt[-1]
    avg12 = sum(usdt[-48:])/48  # media 12 ore
    vol_ok = vol15 >= VOL_MULT * avg12

    # Filtri di sicurezza (trend) per evitare falsi segnali
    ema20 = ema_series(cl[-60:], 20)
    ema60 = ema_series(cl[-60:], 60)
    e20_now, e20_prev, e60_now = ema20[-1], ema20[-2], ema60[-1]
    bull = cl[-1] > op[-1]
    bear = cl[-1] < op[-1]

    # Setup solo se i volumi sono forti; direzione confermata dai filtri minimi
    setup = None
    if vol_ok:
        if e20_now > e60_now and e20_now > e20_prev and bull and cl[-1] >= e20_now:
            setup = "LONG"
        elif e20_now < e60_now and e20_now < e20_prev and bear and cl[-1] <= e20_now:
            setup = "SHORT"

    return {
        "price": cl[-1],
        "vol15": vol15,
        "avg12": avg12,
        "setup": setup,
    }

# ------------------------ TRADE MANAGEMENT -------------------------
def open_trade(sym, side, entry):
    if side == "LONG":
        tp = entry*(1+TP_PCT/100); sl = entry*(1-SL_PCT/100)
    else:
        tp = entry*(1-TP_PCT/100); sl = entry*(1+SL_PCT/100)
    STATE[sym]["trade"] = {"side": side, "entry": entry, "tp": tp, "sl": sl}
    tg(f"🔥 ENTRA {side} {sym}\nPrezzo: {entry:.2f}\nTarget: {tp:.2f}\nStop: {sl:.2f}")

def monitor(sym, price):
    t = STATE[sym]["trade"]
    if not t: return
    if t["side"] == "LONG":
        if price >= t["tp"]:
            tg(f"✅ TP LONG {sym} a {t['tp']:.2f}"); STATE[sym]["trade"] = None
        elif price <= t["sl"]:
            tg(f"❌ STOP LONG {sym} a {t['sl']:.2f}"); STATE[sym]["trade"] = None
    else:
        if price <= t["tp"]:
            tg(f"✅ TP SHORT {sym} a {t['tp']:.2f}"); STATE[sym]["trade"] = None
        elif price >= t["sl"]:
            tg(f"❌ STOP SHORT {sym} a {t['sl']:.2f}"); STATE[sym]["trade"] = None

# ------------------------ SIGNALI (ONLY STRONG) --------------------
def maybe_signal(sym, a):
    side = a["setup"]  # LONG/SHORT/None
    if not side:
        return

    now = time.time()
    # cooldown per evitare ripetizioni stesso lato
    if STATE[sym]["dir"] == side and (now - STATE[sym]["cool_ts"]) < STRONG_COOLD:
        return

    # anti-duplicato su contenuto
    h = hashlib.sha1(f"{sym}|{side}|{a['price']:.2f}|{a['vol15']:.0f}".encode()).hexdigest()
    if h == STATE[sym]["last_sig_hash"] and (now - STATE[sym]["cool_ts"]) < STRONG_COOLD:
        return

    open_trade(sym, side, a["price"])
    STATE[sym]["dir"] = side
    STATE[sym]["cool_ts"] = now
    STATE[sym]["last_sig_hash"] = h

# --------------------------- REPORT --------------------------------
def report_line(sym, a):
    mul = (a["vol15"]/a["avg12"]) if a["avg12"]>0 else 0.0
    setup = a["setup"] if a["setup"] else "nessuno"
    return (f"{sym}: {a['price']:.2f}$ | Vol15m {a['vol15']/1e6:.1f}M "
            f"vs avg {a['avg12']/1e6:.1f}M (x{mul:.2f}) | Setup: {setup}")

def build_report():
    A = {s: analyze(s) for s in ["BTC", "ETH"]}
    if not A["BTC"] or not A["ETH"]:
        return None, None
    it = now_it().strftime("%d/%m %H:%M")
    text = f"🕒 Report {it} (Italia)\n\n{report_line('BTC',A['BTC'])}\n{report_line('ETH',A['ETH'])}"
    return text, A

def send_report_no_dup():
    global LAST_REPORT_HASH, LAST_REPORT_TS
    text, A = build_report()
    if not text: 
        return
    h = hashlib.sha1(text.encode()).hexdigest()
    now = time.time()
    if h == LAST_REPORT_HASH and (now - LAST_REPORT_TS) < REPORT_MIN_GAP:
        return
    tg(text)
    LAST_REPORT_HASH, LAST_REPORT_TS = h, now
    # monitora TP/SL appena dopo
    for s in ["BTC", "ETH"]:
        monitor(s, A[s]["price"])

# -------------------------- SCHEDULER ------------------------------
def next_half_hour_ts():
    t = now_it().replace(second=0, microsecond=0)
    add = 30 - (t.minute % 30)
    if add == 0: add = 30
    return (t + timedelta(minutes=add)).timestamp()

# ----------------------------- MAIN --------------------------------
if not STARTUP_SENT:
    tg("✅ Bot attivo – Segnali con conferma volumi (solo Italia)")
    STARTUP_SENT = True

next_report = next_half_hour_ts()

while True:
    try:
        for s in ["BTC", "ETH"]:
            a = analyze(s)
            if not a: 
                continue
            maybe_signal(s, a)
            monitor(s, a["price"])

        if time.time() >= next_report:
            send_report_no_dup()
            next_report = next_half_hour_ts()

        time.sleep(POLL_SLEEP)

    except Exception:
        # evita crash per errori temporanei (rete/API)
        time.sleep(10)
