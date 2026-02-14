import time
import threading

from steps import prospect
from steps import slugify
from steps import dedup
from steps import synopsis
from steps import review
from steps import covers
from steps import publish   # ← STEP 7

# =========================
# INPUT CONTROL
# =========================

INPUT_MODE = False
last_activity = time.time()


def log(msg):
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


# =========================
# HEARTBEAT
# =========================

def heartbeat():
    global INPUT_MODE

    while True:

        if not INPUT_MODE:
            elapsed = int(time.time() - last_activity)
            log(f"Script ativo… último evento há {elapsed}s")

        time.sleep(30)


threading.Thread(target=heartbeat, daemon=True).start()


# =========================
# INPUT SAFE
# =========================

def input_safe(text):

    global INPUT_MODE

    INPUT_MODE = True
    val = input(text)
    INPUT_MODE = False

    return val


# =========================
# IDIOMA
# =========================

def escolher_idioma():

    print("""
Escolha o idioma base:

1 → Português (padrão)
2 → Inglês
3 → Espanhol
4 → Italiano
""")

    op = input_safe("Idioma: ")

    return {
        "1": "pt",
        "2": "en",
        "3": "es",
        "4": "it"
    }.get(op, "pt")


# =========================
# PACOTE
# =========================

def escolher_pacote():

    print("""
Escolha tamanho do pacote:

10 | 20 | 50 | 100 | 500 | 1000
""")

    return int(input_safe("Pacote: "))


# =========================
# MAIN LOOP
# =========================

def main():

    idioma = escolher_idioma()

    while True:

        print("""
=== LIVRARIA ALEXANDRIA — INGEST PIPELINE ===

1 → Prospectar livros
2 → Gerar slugs
3 → Deduplicar
4 → Gerar sinopses
5 → Revisar sinopses
6 → Gerar capas
7 → Publicar Supabase

0 → Sair
""")

        op = input_safe("Opção: ")

        if op == "0":
            break

        if op == "1":
            pacote = escolher_pacote()
            prospect.run(idioma, pacote)

        elif op == "2":
            pacote = escolher_pacote()
            slugify.run(pacote)

        elif op == "3":
            pacote = escolher_pacote()
            dedup.run(pacote)

        elif op == "4":
            pacote = escolher_pacote()
            synopsis.run(pacote)

        elif op == "5":
            pacote = escolher_pacote()
            review.run(pacote)

        elif op == "6":
            pacote = escolher_pacote()
            covers.run(pacote)

        elif op == "7":
            pacote = escolher_pacote()
            publish.run(pacote)


# =========================
# BOOTSTRAP
# =========================

if __name__ == "__main__":
    main()
