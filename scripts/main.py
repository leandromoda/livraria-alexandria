import time
import threading

from steps import pipeline_status
from steps import offer_seed
from steps import enrich_descricao
from steps import offer_resolver
from steps import slugify
from steps import slugify_autores
from steps import dedup
from steps import dedup_autores
from steps import review
from steps import synopsis
from steps import covers
from steps import quality_gate
from steps import publish
from steps import publish_autores
from steps import publish_ofertas
from steps import list_composer
from steps import auditor
from steps import marketplace_scraper
from steps import categorize
from steps import offer_price_monitor
from steps import publish_categorias
from steps import publish_listas
from steps import repair

from steps.export_state_transcript import export_state_transcript
from steps import db_backup
from steps import db_restore
from steps import db_recover

from core.version import get_version


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
# PROVIDER LLM
# =========================

def escolher_provider():

    print("""
Modelo LLM:

1 → Ollama (local)
2 → Gemini (cloud) [padrão]
3 → Auto (Gemini → Ollama fallback)
""")

    op = input_safe("Modelo: ")

    return {"1": "ollama", "2": "gemini", "3": "auto"}.get(op, "gemini")


# =========================
# MAIN LOOP
# =========================

def main():

    idioma = escolher_idioma()

    while True:

        print("""
=== LIVRARIA ALEXANDRIA — INGEST PIPELINE ===

S  → Status do pipeline (gargalos)

--- INGESTÃO ---
1  → Importar Offer Seeds
2  → Enriquecer descrições (Google Books / OpenLibrary)
3  → Resolver Ofertas (lookup → URL afiliado)
4  → Enriquecer via Marketplace Scraper (capa + descrição + preço)

--- PRÉ-PROCESSAMENTO ---
5  → Gerar slugs
6  → Slugify Autores
7  → Deduplicar Autores
8  → Deduplicar
9  → Review (classificação editorial + idioma)
10 → Classificar Categorias Temáticas (LLM)

--- GERAÇÃO DE CONTEÚDO ---
11 → Gerar sinopses (requer review concluído)
12 → Gerar capas

--- PUBLICAÇÃO ---
13 → Quality Gate
14 → Publicar Supabase
15 → Publicar Autores
16 → Publicar Categorias (requer step 10)
17 → Publicar Ofertas
18 → Gerar listas SEO automáticas
19 → Publicar Listas (requer step 18)

--- MONITORAMENTO ---
20 → Monitorar preços e disponibilidade de ofertas

--- AUDITORIA ---
21 → Auditar conectividade do site (sem LLM)
22 → Auditar conteúdo publicado (LLM)
23 → Reparar publicações com dados ruins (sinopse, capa, preço)

--- BANCO DE DADOS ---
95 → Fazer backup do banco local
96 → Restaurar banco de backup
97 → Recuperar banco do Supabase + backup

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

        elif op in ("s", "S"):
            pipeline_status.run()

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
            log("Enriquecendo via Marketplace Scraper…")
            marketplace_scraper.run(idioma, pacote)

        elif op == "5":
            pacote = escolher_pacote()
            slugify.run(idioma, pacote)

        elif op == "6":
            log("Slugificando autores…")
            slugify_autores.run()

        elif op == "7":
            log("Deduplicando autores…")
            dedup_autores.run()

        elif op == "8":
            pacote = escolher_pacote()
            dedup.run(idioma, pacote)

        elif op == "9":
            pacote = escolher_pacote()
            review.run(idioma, pacote)

        elif op == "10":
            pacote = escolher_pacote()
            reset = input_safe("Resetar livros com falha anterior? [s/N] ").strip().lower()
            if reset == "s":
                categorize.reset_failed()
            from core.markdown_executor import set_provider
            set_provider(escolher_provider())
            log("Classificando categorias temáticas…")
            categorize.run(idioma, pacote)

        elif op == "11":
            pacote = escolher_pacote()
            from core.markdown_executor import set_provider
            set_provider(escolher_provider())
            synopsis.run(idioma, pacote)

        elif op == "12":
            pacote = escolher_pacote()
            covers.run(idioma, pacote)

        elif op == "13":
            pacote = escolher_pacote()
            quality_gate.evaluate_quality(idioma, pacote)

        elif op == "14":
            pacote = escolher_pacote()
            publish.run(idioma, pacote)

        elif op == "15":
            pacote = escolher_pacote()
            log("Publicando autores no Supabase…")
            publish_autores.run(pacote)

        elif op == "16":
            log("Publicando categorias temáticas no Supabase…")
            publish_categorias.run()

        elif op == "17":
            pacote = escolher_pacote()
            log("Publicando ofertas no Supabase…")
            publish_ofertas.run(pacote)

        elif op == "18":
            log("Gerando listas SEO automáticas…")
            list_composer.run()

        elif op == "19":
            log("Publicando listas no Supabase…")
            publish_listas.run()

        elif op == "20":
            print("""
Limite de livros para monitorar:

10 | 20 | 50 | 100 | 200
""")
            try:
                limite = int(input_safe("Limite: "))
            except ValueError:
                limite = 50

            dry_op  = input_safe("Dry-run? (s/N): ").strip().lower()
            dry_run = dry_op == "s"

            log(f"Monitorando preços e disponibilidade (limit={limite}, dry_run={dry_run})…")
            offer_price_monitor.run(limit=limite, dry_run=dry_run)

        elif op == "21":
            log("Auditando conectividade do site…")
            import argparse
            args = argparse.Namespace(mode="connectivity", dry_run=False)
            auditor.run(args)

        elif op == "22":
            print("""
Limite de livros para auditoria:

10 | 20 | 50 | 100
""")
            try:
                limite = int(input_safe("Limite: "))
            except ValueError:
                limite = 20

            dry_op = input_safe("Dry-run? (s/N): ").strip().lower()
            dry_run = dry_op == "s"

            from core.markdown_executor import set_provider
            set_provider(escolher_provider())

            log(f"Auditando conteúdo publicado (limit={limite}, dry_run={dry_run})…")
            import argparse
            args = argparse.Namespace(mode="content", limit=limite, dry_run=dry_run)
            auditor.run(args)

        elif op == "23":
            log("Reparando publicações com dados ruins…")
            repair.run()

        elif op == "95":
            log("Fazendo backup do banco local…")
            db_backup.run()

        elif op == "96":
            log("Restaurando banco de backup…")
            db_restore.run()

        elif op == "97":
            log("Recuperando banco do Supabase + backup local…")
            db_recover.run()

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
            continue

        log(f"[PIPELINE] v{get_version()}")


# =========================
# BOOTSTRAP
# =========================

if __name__ == "__main__":
    main()
