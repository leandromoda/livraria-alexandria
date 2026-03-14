import time
import threading

from steps import offer_seed
from steps import enrich_descricao
from steps import offer_resolver
from steps import slugify
from steps import slugify_autores
from steps import dedup
from steps import review
from steps import synopsis
from steps import covers
from steps import quality_gate
from steps import publish
from steps import publish_autores
from steps import list_composer

from steps.export_state_transcript import export_state_transcript


# =========================
# INPUT CONTROL
# =========================

INPUT_MODE    = False
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
    val        = input(text)
    INPUT_MODE = False

    last_activity = time.time()

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

    return {"1": "PT", "2": "EN", "3": "ES", "4": "IT"}.get(op, "PT")


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

--- INGESTÃO ---
1  → Importar Offer Seeds
2  → Enriquecer descrições (Google Books)
3  → Resolver Ofertas (lookup → URL afiliado)

--- PRÉ-PROCESSAMENTO ---
4  → Gerar slugs
5  → Slugify Autores
6  → Deduplicar
7  → Review (classificação editorial + idioma)

--- GERAÇÃO DE CONTEÚDO ---
8  → Gerar sinopses (requer review concluído)
9  → Gerar capas

--- PUBLICAÇÃO ---
10 → Quality Gate
11 → Publicar Supabase
12 → Publicar Autores
13 → Gerar listas SEO automáticas

--- EXPORTS ---
91 → Export Site Bootstrap
92 → Export Pipeline Summary
93 → Export Database Transcript
94 → Export Project Tree (JSON)

0  → Sair
""")

        op = input_safe("Opção: ")

        if op == "0":
            break

        elif op == "1":
            log("Importando Offer Seeds…")
            offer_seed.run()

        elif op == "2":
            pacote = escolher_pacote()
            log("Enriquecendo descrições via Google Books…")
            enrich_descricao.run(pacote)

        elif op == "3":
            pacote = escolher_pacote()
            log("Resolvendo ofertas reais…")
            offer_resolver.run(idioma, pacote)

        elif op == "4":
            pacote = escolher_pacote()
            slugify.run(idioma, pacote)

        elif op == "5":
            log("Slugificando autores…")
            slugify_autores.run()

        elif op == "6":
            pacote = escolher_pacote()
            dedup.run(idioma, pacote)

        elif op == "7":
            pacote = escolher_pacote()
            review.run(idioma, pacote)

        elif op == "8":
            pacote = escolher_pacote()
            synopsis.run(idioma, pacote)

        elif op == "9":
            pacote = escolher_pacote()
            covers.run(idioma, pacote)

        elif op == "10":
            pacote = escolher_pacote()
            quality_gate.evaluate_quality(idioma, pacote)

        elif op == "11":
            pacote = escolher_pacote()
            publish.run(idioma, pacote)

        elif op == "12":
            log("Publicando autores no Supabase…")
            publish_autores.run()

        elif op == "13":
            log("Gerando listas SEO automáticas…")
            list_composer.run()

        elif op == "91":
            log("Exportando Site Bootstrap…")
            export_state_transcript("site")

        elif op == "92":
            log("Exportando Pipeline Summary…")
            export_state_transcript("pipeline_summary")

        elif op == "93":
            log("Exportando Database Transcript…")
            export_state_transcript("database")

        elif op == "94":
            log("Exportando Project Tree…")
            export_state_transcript("project_tree")

        else:
            print("Opção inválida.\n")


# =========================
# BOOTSTRAP
# =========================

if __name__ == "__main__":
    main()
