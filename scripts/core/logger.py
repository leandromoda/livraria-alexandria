import time
import threading
from datetime import datetime

last_activity = time.time()


def log(msg):

    global last_activity

    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

    last_activity = time.time()


def start_heartbeat():

    def beat():

        while True:

            elapsed = int(time.time() - last_activity)

            now = datetime.now().strftime("%H:%M:%S")
            print(f"[{now}] Script ativo… último evento há {elapsed}s")

            time.sleep(30)

    threading.Thread(target=beat, daemon=True).start()
