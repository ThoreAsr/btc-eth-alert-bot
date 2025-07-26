import os
import time
import requests

# Recupera token e chat_id dalle variabili d'ambiente su Render
TOKEN = os.getenv("Token")
CHAT_ID = os.getenv("Chat_Id")

def manda_messaggio(testo):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    dati = {"chat_id": CHAT_ID, "text": testo}
    try:
        requests.post(url, data=dati)
    except Exception as e:
        print("Errore invio messaggio:", e)

# Messaggio di avvio
manda_messaggio("✅ TEST: Bot attivo su Render. Messaggi ogni 5 minuti.")

# Ciclo infinito: messaggio ogni 5 minuti
while True:
    manda_messaggio("🔔 Test: il bot su Render è attivo e sta inviando messaggi.")
    time.sleep(300)  # 300 secondi = 5 minuti
