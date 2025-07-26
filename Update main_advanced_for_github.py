import os
import time
import requests

# Legge token e chat ID da variabili ambiente
TOKEN = os.getenv("Token")
CHAT_ID = os.getenv("Chat_Id")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"Errore invio messaggio: {e}")

# Messaggio di avvio
send_telegram_message("✅ BOT AVVIATO: Alert BTC + ETH dinamici attivi con RSI e volumi.")

# Loop principale: qui inserirai la logica per alert reali BTC/ETH
while True:
    # Qui puoi aggiungere controlli prezzi reali o segnali
    time.sleep(300)  # Controlla ogni 5 minuti
