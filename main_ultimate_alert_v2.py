#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BOT FAMIGLIA – Apple Watch friendly (pulito e operativo)
- Niente spam: di default invia SOLO quando c'è un breakout/breakdown reale
- Messaggi super compatti e leggibili su Apple Watch
- Trend: EMA(15) vs EMA(50) su 15m e 30m
- Livelli: max/min ultime 48 candele 15m (≈12h)
- Multi-simbolo: di default BTCUSDT e ETHUSDT (configurabile)
- Loop continuo con sleep configurabile

ENV richieste su Render (Environment):
  TELEGRAM_BOT_TOKEN   = <token bot>
  TELEGRAM_CHAT_ID     = 356760541  (o il tuo chat id)
Opzionali:
  SYMBOLS              = BTCUSDT,ETHUSDT
  LOOP_SECONDS         = 60          (controllo ogni 60s)
  SEND_HEARTBEAT       = false       (true/false) – se true, manda 1 msg ogni INTERVAL_MINUTES
  INTERVAL_MINUTES     = 15          (frequenza heartbeat, se abilitato)

Start Command (Render):
  python main_ultimate_alert_v2.py
"""

import os
import time
import math
from typing import List, Tuple, Dict
import requests
from datetime import datetime, timezone

BINANCE_BASE = "https://api.binance.com"

def env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, str(default)).strip().lower()
    return v in ("1", "true", "yes", "y", "on")

def get_symbols() -> List[str]:
    raw = os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
LOOP_SECONDS = int(os.environ.get("LOOP_SECONDS", "60"))
SEND_HEARTBEAT = env_bool("SEND_HEARTBEAT", False)
INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "15"))

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Devi impostare TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nelle Environment Variables di Render.")

# -------------------- Data fetch --------------------

def fetch_price(symbol: str) -> float:
    r = requests.get(f"{BINANCE_BASE}/api/v3/ticker/price",
                     params={"symbol": symbol}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])

def fetch_klines(symbol: str, interval: str, limit: int = 200) -> List[List]:
    r = requests.get(f"{BINANCE_BASE}/api/v3/klines",
                     params={"symbol": symbol, "interval": interval, "limit": limit},
                     timeout=15)
    r.raise_for_status()
    return r.json()

# -------------------- Indicators --------------------

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

def compute_levels_from_swings(highs: List[float], lows: List[float], window: int = 48) -> Tuple[float, float]:
    if len(highs) < window or len(lows) < window:
        window = min(len(highs), len(lows))
    return max(highs[-window:]), min(lows[-window:])

# -------------------- Formatting --------------------

def round_nice_level(x: float) -> str:
    step = 100 if x >= 10000 else 50
    y = round(x / step) * step
    if y >= 1000:
        if y % 1000 == 0:
            return f"{int(y/1000)}k"
        return f"{y/1000:.1f}k"
    return f"{int(y)}"

def fmt_price_watch(p: float) -> str:
    # 112.100$ -> stile Europeo (punti per migliaia) per compattezza
    return f"{p:,.0f}$".replace(",", ".")

def build_msg(symbol: str, price: float, trend15: str, trend30: str, res: float, sup: float) -> str:
    res_s = round_nice_level(res)
    sup_s = round_nice_level(sup)
    return (
        f"🚨 {symbol}\n"
        f"💵 {fmt_price_watch(price)}\n"
        f"📈 15m: {trend15} | 30m: {trend30}\n"
        f"🔑 Res: {res_s} | Sup: {sup_s}\n"
        f"👉 Buy >{res_s} | Sell <{sup_s}"
    )

def build_hb(symbol: str, price: float, trend15: str, trend30: str, res: float, sup: float) -> str:
    # Heartbeat compatto (se abilitato)
    res_s = round_nice_level(res)
    sup_s = round_nice_level(sup)
    return (
        f"🫀 {symbol}\n"
        f"💵 {fmt_price_watch(price)}  | 15m:{trend15} / 30m:{trend30}\n"
        f"R:{res_s} S:{sup_s}"
    )

# -------------------- Telegram --------------------

def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    r = requests.post(url, data=payload, timeout=15)
    r.raise_for_status()

# -------------------- Core logic --------------------

class WatchState:
    def __init__(self):
        self.last_cross_side: Dict[str, str] = {}  # 'above'|'below'|'between'
        self.last_hb_minute: int = -1

STATE = WatchState()

def side_vs_band(price: float, sup: float, res: float) -> str:
    if price > res:
        return "above"
    if price < sup:
        return "below"
    return "between"

def process_symbol(symbol: str) -> None:
    # 15m for levels/trend; 30m for second trend
    kl15 = fetch_klines(symbol, "15m", 200)
    kl30 = fetch_klines(symbol, "30m", 200)

    closes15 = [float(k[4]) for k in kl15]
    highs15  = [float(k[2]) for k in kl15]
    lows15   = [float(k[3]) for k in kl15]
    closes30 = [float(k[4]) for k in kl30]

    res, sup = compute_levels_from_swings(highs15, lows15, 48)
    trend15 = trend_from_ema(closes15, 15, 50)
    trend30 = trend_from_ema(closes30, 15, 50)
    price = fetch_price(symbol)

    # breakout logic
    now_side = side_vs_band(price, sup, res)
    prev_side = STATE.last_cross_side.get(symbol, "between")
    STATE.last_cross_side[symbol] = now_side

    # Heartbeat (se attivo, 1 volta ogni INTERVAL_MINUTES)
    if SEND_HEARTBEAT:
        now_min = int(time.time() // 60)
        if now_min % INTERVAL_MINUTES == 0 and STATE.last_hb_minute != now_min:
            STATE.last_hb_minute = now_min
            send_telegram(build_hb(symbol, price, trend15, trend30, res, sup))

    # Invio solo su cambi significativi di stato (breakout/breakdown)
    fired = False
    if prev_side != now_side:
        # appena passa da between -> above = breakout
        # appena passa da between -> below = breakdown
        # oppure attraversamenti opposti
        msg = build_msg(symbol, price, trend15, trend30, res, sup)
        send_telegram(msg)
        fired = True

    # Se vuoi anche 1° messaggio all’avvio per avere lo stato iniziale:
    if prev_side == "between" and not fired:
        # invia 1 messaggio di setup all'avvio del servizio
        if "initialized_"+symbol not in STATE.last_cross_side:
            send_telegram(build_msg(symbol, price, trend15, trend30, res, sup))
            STATE.last_cross_side["initialized_"+symbol] = "yes"

def main_loop():
    symbols = get_symbols()
    while True:
        try:
            for s in symbols:
                process_symbol(s)
        except Exception as e:
            try:
                send_telegram(f"⚠️ Errore: {e}")
            except Exception:
                pass
        time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main_loop()
