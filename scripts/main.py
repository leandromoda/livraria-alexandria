import time
import threading

from steps import prospect
from steps import slugify
from steps import dedup
from steps import synopsis
from steps import review
from steps import covers
from steps import publish
from steps import quality_gate

from steps.export_state_transcript import export_state_transcript


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

    global INPUT_MODE, last_activity

    INPUT_MODE = True
    val = input(text)
    INPUT_MODE = False

    last_activity = time.time()

    return val


# =========================
# IDIOMA (ISO NORMALIZADO)
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
        "1": "PT",
        "2": "EN",
        "3": "ES",
        "4": "IT"
    }.get(op, "PT")


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
7 → Quality Gate
8 → Publicar Supabase

9 → Export Site Transcript
10 → Export Pipeline Transcript
11 → Export Full Transcript

0 → Sair
""")

        op = input_safe("Opção: ")

        if op == "0":
            break

        elif op == "1":
            pacote = escolher_pacote()
            prospect.run(idioma, pacote)

        elif op == "2":
            pacote = escolher_pacote()
            slugify.run(idioma, pacote)

        elif op == "3":
            pacote = escolher_pacote()
            dedup.run(idioma, pacote)

        elif op == "4":
            pacote = escolher_pacote()
            synopsis.run(idioma, pacote)

        elif op == "5":
            pacote = escolher_pacote()
            review.run(idioma, pacote)

        elif op == "6":
            pacote = escolher_pacote()
            covers.run(idioma, pacote)

        elif op == "7":
            pacote = escolher_pacote()
            log("Executando Quality Gate…")
            quality_gate.evaluate_quality(idioma, pacote)
            log("Quality Gate concluído.")

        elif op == "8":
            pacote = escolher_pacote()
            publish.run(idioma, pacote)

        elif op == "9":
            log("Exportando Site Transcript…")
            export_state_transcript("site")
            log("Concluído.")

        elif op == "10":
            log("Exportando Pipeline Transcript…")
            export_state_transcript("pipeline")
            log("Concluído.")

        elif op == "11":
            log("Exportando Full Transcript…")
            export_state_transcript("full")
            log("Concluído.")

        else:
            print("Opção inválida.\n")


# =========================
# BOOTSTRAP
# =========================

if __name__ == "__main__":
    main()
