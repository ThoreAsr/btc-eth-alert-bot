import os
import time
import traceback

def check_env():
    # Controllo variabili d'ambiente necessarie
    required_vars = ["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]
    for var in required_vars:
        if not os.getenv(var):
            print(f"ERRORE: Variabile d'ambiente mancante -> {var}")
            return False
    return True

def start_bot():
    print("=== BOT BTC/ETH AVVIATO SU RENDER ===")

    # Controllo iniziale ambiente
    if not check_env():
        print("Configura le variabili d'ambiente su Render (Settings > Environment).")
        return

    # Loop principale
    while True:
        try:
            # Qui metti la logica del tuo bot: lettura prezzi BTC/ETH e invio alert
            print("Controllo prezzi BTC/ETH...")  # debug visibile nei Logs di Render

            # Esempio: dorme 30 secondi
            time.sleep(30)

        except Exception as e:
            print("Errore nel ciclo principale:", e)
            traceback.print_exc()
            # Aspetta 5 secondi e riprova
            time.sleep(5)

if __name__ == "__main__":
    start_bot()
