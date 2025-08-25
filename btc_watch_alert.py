#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BTC Apple Watch Alert — compatto e operativo
- Prezzo in prima riga
- Trend 15m/30m (EMA 15 vs EMA 50)
- Un supporto e una resistenza principali (calcolati da recenti swing)
- Segnale operativo sintetico (buy/sell oltre i livelli)
Uso:
  export TELEGRAM_BOT_TOKEN="..."
  export TELEGRAM_CHAT_ID="..."
  python3 btc_watch_alert.py [--loop 900]
"""

import os
import time
import math
import argparse
from typing import List, Tuple
import requests

BINANCE_BASE = "https://api.binance.com"
SYMBOL = "BTCUSDT"

def fetch_price() -> float:
    r = requests.get(f"{BINANCE_BASE}/api/v3/ticker/price", params={"symbol": SYMBOL}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])

def fetch_klines(interval: str, limit: int = 200) -> List[List]:
    # kline fields: [openTime, open, high, low, close, volume, closeTime, ...]
    r = requests.get(f"{BINANCE_BASE}/api/v3/klines", params={"symbol": SYMBOL, "interval": interval, "limit": limit}, timeout=15)
    r.raise_for_status()
    return r.json()

def ema(values: List[float], length: int) -> List[float]:
    if not values or length <= 0 or len(values) < length:
        return []
    k = 2 / (length + 1)
    ema_vals = [sum(values[:length]) / length]
    for v in values[length:]:
        ema_vals.append(v * k + ema_vals[-1] * (1 - k))
    # pad left to match length
    pad = [None] * (len(values) - len(ema_vals))
    return pad + ema_vals

def trend_from_ema(closes: List[float], fast_len=15, slow_len=50) -> str:
    efast = ema(closes, fast_len)
    eslow = ema(closes, slow_len)
    if not efast or not eslow or efast[-1] is None or eslow[-1] is None:
        return "n/d"
    if efast[-1] > eslow[-1]:
        return "rialzo"
    elif efast[-1] < eslow[-1]:
        return "ribasso"
    return "neutro"

def round_nice_level(x: float) -> str:
    """
    Arrotonda in modo “pulito” per display su Watch:
    - sopra 10k usa step 100
    - sotto 10k usa step 50
    Restituisce stringa corta (es. '113k' o '111.5k' se appropriato).
    """
    step = 100 if x >= 10000 else 50
    y = round(x / step) * step
    # Formattazione breve
    if y >= 1000:
        # prova con k intero se è tondo
        if y % 1000 == 0:
            return f"{int(y/1000)}k"
        # altrimenti una cifra decimale
        return f"{y/1000:.1f}k"
    return f"{int(y)}"

def compute_levels_from_swings(highs: List[float], lows: List[float], window: int = 48) -> Tuple[float, float]:
    """
    Prende gli ultimi 'window' candele (circa 12h su 15m) e usa
    max(high) come resistenza e min(low) come supporto.
    """
    if len(highs) < window or len(lows) < window:
        window = min(len(highs), len(lows))
    h = max(highs[-window:])
    l = min(lows[-window:])
    return h, l

def build_message(price: float,
                  trend15: str,
                  trend30: str,
                  res: float,
                  sup: float) -> str:
    price_str = f"{price:,.0f}$".replace(",", ".")  # es: 112.100$
    res_str = round_nice_level(res)
    sup_str = round_nice_level(sup)

    # Direzione operativa sintetica
    # buy sopra resistenza, sell sotto supporto
    msg = (
        f"🚨 BTC/USDT\n"
        f"💵 {price_str}\n"
        f"📈 15m: {trend15} | 30m: {trend30}\n"
        f"🔑 Res: {res_str} | Sup: {sup_str}\n"
        f"👉 Buy >{res_str} | Sell <{sup_str}"
    )
    return msg

def send_telegram(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Devi impostare TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nell'ambiente.")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }
    r = requests.post(url, data=payload, timeout=15)
    r.raise_for_status()

def run_once(verbose: bool = True) -> str:
    # Dati 15m (per trend e livelli) e 30m (trend)
    kl15 = fetch_klines("15m", limit=200)
    kl30 = fetch_klines("30m", limit=200)

    closes15 = [float(k[4]) for k in kl15]
    highs15  = [float(k[2]) for k in kl15]
    lows15   = [float(k[3]) for k in kl15]

    closes30 = [float(k[4]) for k in kl30]

    trend15 = trend_from_ema(closes15, 15, 50)
    trend30 = trend_from_ema(closes30, 15, 50)

    res, sup = compute_levels_from_swings(highs15, lows15, window=48)

    price = fetch_price()

    msg = build_message(price, trend15, trend30, res, sup)

    if verbose:
        print(msg)
    send_telegram(msg)
    return msg

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", type=int, default=0, help="Esegue in loop ogni N secondi (es. 900 per 15m). 0 = one-shot.")
    args = parser.parse_args()

    if args.loop and args.loop > 0:
        while True:
            try:
                run_once(verbose=True)
            except Exception as e:
                print(f"[ERRORE] {e}")
            time.sleep(args.loop)
    else:
        try:
            run_once(verbose=True)
        except Exception as e:
            print(f"[ERRORE] {e}")
            raise

if __name__ == "__main__":
    main()
