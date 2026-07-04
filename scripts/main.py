import argparse
import sys
import time
import threading

# Console do Windows costuma usar cp1252; força UTF-8 no stdout/stderr para os
# painéis e box-chars (─, █, →, ↓) não quebrarem com UnicodeEncodeError.
# Idempotente e seguro (reconfigure existe em Python 3.7+).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

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
from steps import targeted_repair
from steps import apply_blacklist
from steps import autopilot
from steps import llm_orchestrator
from steps import autopilot_audit
from steps import autopilot_manutencao
from steps import ingestao_orientada
from steps import priority_scorer
from steps import author_bio
from steps import offer_list_importer
from steps import fix_affiliate_urls
from steps import synopsis_export
from steps import synopsis_import
from steps import categorize_export
from steps import categorize_import
from steps import batch_export
from steps import batch_import
from steps import consistency_check
from steps import reprocess_blacklist
from steps import qa
from core import export_for_audit as _export_for_audit

from steps.export_state_transcript import export_state_transcript
from steps import db_backup
from steps import db_restore
from steps import db_recover

from core.db import get_conn
from core.version import get_version
from core.run_logger import StepRun


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

1 → Claude (API) [padrão]
2 → Gemini (cloud)
3 → Ollama (local)
4 → Auto (Gemini → Ollama fallback)
""")

    op = input_safe("Modelo: ")

    return {"1": "claude", "2": "gemini", "3": "ollama", "4": "auto"}.get(op, "claude")


# =========================
# SUBMENUS
# =========================

def menu_ingestao(idioma):
    while True:
        print("""
--- INGESTÃO ---

1  → Importar Offer Seeds
2  → Enriquecer descrições (Google Books / OpenLibrary) [fallback manual — coberto pelo step 4]
3  → Resolver Ofertas (lookup → URL afiliado)
4  → Enriquecer via Marketplace Scraper (capa + descrição + preço)

V  → Voltar
""")
        op = input_safe("Opção: ")

        if op.upper() == "V":
            break

        elif op == "1":
            log("Importando Offer Seeds…")
            with StepRun("offer_seed", idioma=idioma):
                offer_seed.run()

        elif op == "2":
            pacote = escolher_pacote()
            retry = input_safe(
                "Reprocessar também os que falharam antes (status=2)? "
                "Recupera livros via autor + descrição multi-idioma. [s/N] "
            ).strip().lower() == "s"
            log("Enriquecendo descrições via Google Books…")
            with StepRun("enrich_descricao", idioma=idioma, pacote=pacote):
                enrich_descricao.run(pacote, retry_failed=retry)

        elif op == "3":
            pacote = escolher_pacote()
            todos = input_safe("Processar todos os idiomas, incluindo UNKNOWN (recomendado)? [S/n] ").strip().lower()
            idioma_resolver = None if todos != "n" else idioma
            log("Resolvendo ofertas reais…")
            with StepRun("offer_resolver", idioma=idioma, pacote=pacote):
                offer_resolver.run(idioma_resolver, pacote)

        elif op == "4":
            pacote = escolher_pacote()
            log("Enriquecendo via Marketplace Scraper…")
            with StepRun("marketplace_scraper", idioma=idioma, pacote=pacote):
                marketplace_scraper.run(idioma, pacote)

        else:
            print("Opção inválida.\n")
            continue

        log(f"[PIPELINE] v{get_version()}")


def menu_preprocessamento(idioma):
    while True:
        print("""
--- PRÉ-PROCESSAMENTO ---

5  → Gerar slugs
6  → Slugify Autores
7  → Deduplicar Autores
8  → Deduplicar
9  → Review (classificação editorial + idioma)

V  → Voltar
""")
        op = input_safe("Opção: ")

        if op.upper() == "V":
            break

        elif op == "5":
            pacote = escolher_pacote()
            with StepRun("slugify", idioma=idioma, pacote=pacote):
                slugify.run(idioma, pacote)

        elif op == "6":
            pacote = escolher_pacote()
            log("Slugificando autores…")
            with StepRun("slugify_autores", idioma=idioma, pacote=pacote):
                slugify_autores.run(pacote)

        elif op == "7":
            log("Deduplicando autores…")
            with StepRun("dedup_autores", idioma=idioma):
                dedup_autores.run()

        elif op == "8":
            pacote = escolher_pacote()
            with StepRun("dedup", idioma=idioma, pacote=pacote):
                dedup.run(idioma, pacote)

        elif op == "9":
            pacote = escolher_pacote()
            with StepRun("review", idioma=idioma, pacote=pacote):
                review.run(idioma, pacote)

        else:
            print("Opção inválida.\n")
            continue

        log(f"[PIPELINE] v{get_version()}")


def menu_geracao_conteudo(idioma):
    while True:
        print("""
--- GERAÇÃO DE CONTEÚDO ---

10  → Classificar Categorias Temáticas (LLM)
10R → Resetar categoria equivocada (limpa e recategoriza)
11  → Gerar sinopses (LLM) (requer review concluído)
12  → Gerar capas
13  → Gerar Bios de Autores (LLM)

V  → Voltar
""")
        op = input_safe("Opção: ")

        if op.upper() == "V":
            break

        elif op == "10":
            pacote = escolher_pacote()
            reset = input_safe("Resetar livros com falha anterior? [s/N] ").strip().lower()
            if reset == "s":
                categorize.reset_failed()
            # Motor único: agente batch classify_batch via Claude CLI (sem escolha de provider).
            log("Classificando categorias temáticas…")
            with StepRun("categorize", idioma=idioma, pacote=pacote):
                categorize.run(idioma, pacote)

        elif op.upper() == "10R":
            from core.db import get_conn as _get_conn
            slug = input_safe("Slug da categoria a resetar (ex: historia-antiga): ").strip()
            if not slug:
                print("Slug inválido.")
                continue
            conn_r = _get_conn()
            afetados = categorize.reset_wrong_category(conn_r, slug)
            conn_r.close()
            if afetados:
                print(f"\n{len(afetados)} livro(s) tiveram a categorização apagada e status_categorize=0.")
                print("Próximos passos:")
                print("  1. Rode a opção 10 (Classificar Categorias Temáticas) para recategorizar.")
                print("  2. Rode o step 23 (Publicar Categorias) para atualizar o Supabase.")
                print("  3. No Supabase, delete manualmente as entradas antigas de 'livros_categorias'")
                print(f"     para a categoria '{slug}' que não foram substituídas.")
            else:
                print(f"Nenhum livro encontrado com a categoria '{slug}'.")

        elif op == "11":
            pacote = escolher_pacote()
            # Motor único: agente batch synopsis_batch via Claude CLI (sem escolha de provider).
            with StepRun("synopsis", idioma=idioma, pacote=pacote):
                synopsis.run(idioma, pacote)

        elif op == "12":
            pacote = escolher_pacote()
            with StepRun("covers", idioma=idioma, pacote=pacote):
                covers.run(idioma, pacote)

        elif op == "13":
            pacote = escolher_pacote()
            from core.markdown_executor import set_provider
            set_provider(escolher_provider())
            log("Gerando bios de autores (LLM)…")
            with StepRun("author_bio", idioma=idioma, pacote=pacote):
                author_bio.run(idioma, pacote)

        else:
            print("Opção inválida.\n")
            continue

        log(f"[PIPELINE] v{get_version()}")


def menu_publicacao(idioma):
    while True:
        print("""
--- PUBLICAÇÃO ---

20 → Quality Gate
21 → Publicar Supabase
22 → Publicar Autores
23 → Publicar Categorias (requer step 10)
24 → Publicar Ofertas
25 → Gerar listas SEO automáticas
26 → Publicar Listas (requer step 25)
27 → Reparar Ofertas (força republicação de todas para livros publicados)
28 → Fix Affiliate URLs (corrige URLs sem parâmetros de comissão)
29 → Importar offer_list.json (agente offer_finder → SQLite + Supabase)
30 → Reparar Relações Autores-Livros (re-sincroniza livros_autores no Supabase)

V  → Voltar
""")
        op = input_safe("Opção: ")

        if op.upper() == "V":
            break

        elif op == "20":
            pacote = escolher_pacote()
            with StepRun("quality_gate", idioma=idioma, pacote=pacote):
                quality_gate.evaluate_quality(idioma, pacote)

        elif op == "21":
            pacote = escolher_pacote()
            with StepRun("publish", idioma=idioma, pacote=pacote):
                publish.run(idioma, pacote)

        elif op == "22":
            pacote = escolher_pacote()
            log("Publicando autores no Supabase…")
            with StepRun("publish_autores", idioma=idioma, pacote=pacote):
                publish_autores.run(pacote)

        elif op == "23":
            log("Publicando categorias temáticas no Supabase…")
            with StepRun("publish_categorias", idioma=idioma):
                publish_categorias.run()

        elif op == "24":
            fix = input_safe("Normalizar offer_status='active' → 1 (recomendado na 1ª vez)? [s/N] ").strip().lower()
            if fix == "s":
                publish_ofertas.fix_offer_status()
            pacote = escolher_pacote()
            log("Publicando ofertas no Supabase…")
            with StepRun("publish_ofertas", idioma=idioma, pacote=pacote):
                publish_ofertas.run(pacote)

        elif op == "25":
            log("Gerando listas SEO automáticas…")
            with StepRun("list_composer", idioma=idioma):
                list_composer.run()

        elif op == "26":
            log("Publicando listas no Supabase…")
            with StepRun("publish_listas", idioma=idioma):
                publish_listas.run()

        elif op == "27":
            pacote = escolher_pacote()
            log("Reparando ofertas — forçando republicação para todos os livros publicados…")
            with StepRun("publish_ofertas_repair", idioma=idioma, pacote=pacote):
                publish_ofertas.run_repair(pacote)

        elif op == "28":
            log("Corrigindo URLs de afiliado sem parâmetros de comissão…")
            with StepRun("fix_affiliate_urls", idioma=idioma):
                fix_affiliate_urls.run()

        elif op == "29":
            pacote = escolher_pacote()
            log("Importando offer_list.json (agente offer_finder)…")
            with StepRun("offer_list_importer", idioma=idioma, pacote=pacote):
                offer_list_importer.run(pacote)

        elif op == "30":
            log("Re-sincronizando relações livros_autores no Supabase…")
            with StepRun("repair_relacoes_autores", idioma=idioma):
                publish_autores.run_repair_relacoes()

        else:
            print("Opção inválida.\n")
            continue

        log(f"[PIPELINE] v{get_version()}")


def menu_auditoria(idioma):
    while True:
        print("""
--- AUDITORIA E MONITORAMENTO ---

40 → Monitorar preços e disponibilidade de ofertas
41 → Auditar conectividade do site (sem LLM) → data/logs/NNNN_audit_connectivity.json
42 → Auditar conteúdo publicado (LLM) → data/logs/NNNN_audit_content.json
43 → Reparar publicações com dados ruins (sinopse, capa, preço)
44 → Reparo Direcionado por Slug (reset sinopse | capa | ambos)
45 → Aplicar Blacklist (despublicar via blacklist.json do agente auditor)
46 → Exportar livros para auditoria (gera audit_input.json para Claude Code)
47 → Auditoria de Integridade (sem LLM — verifica consistência do pipeline)
48 → Auditar listas SEO (sem LLM) → data/logs/NNNN_audit_list.json
49 → Verificar autores sem bio (sem LLM) → data/logs/NNNN_audit_author_bio.json
50 → Verificar veracidade de títulos (Google Books + LLM) → audit_log mode=title_verify
51 → Gerar relatório de consistência (Supabase) → data/batch/YYYYMMDDHHMMSS_consistency.json
52 → Reprocessar blacklist (recupera por causa / quarentena) [WS5]
53 → QA — passe de remediação (aplica blacklist → reprocessa) [WS4]
54 → Auditar capas (sem LLM) → data/logs/NNNN_audit_covers.json
55 → Auditar classificação (sem LLM) → data/logs/NNNN_audit_classification.json
56 → QA — Auditoria completa do site (sem LLM): conexões+preços+capas+classificação+listas+integridade+consistência
57 → QA — Passe completo (auditoria do site + remediação)
58 → QA — Remediação de capas (reprocessa publicados sem capa, com prioridade)
59 → QA — Reconcile de sinopse (status_synopsis=0 c/ texto válido → flag + QG + publish, sem LLM)
60 → QA — Marcar sinopses inválidas p/ regeneração (status_synopsis=1 ruim → 0; o O/G regenera)
61 → QA — Ingerir relatórios de auditoria na fila de remediação (P1 → fila; sem LLM)

V  → Voltar
""")
        op = input_safe("Opção: ")

        if op.upper() == "V":
            break

        elif op == "40":
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

        elif op == "41":
            log("Auditando conectividade do site…")
            args = argparse.Namespace(mode="connectivity", dry_run=False)
            auditor.run(args)

        elif op == "42":
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
            args = argparse.Namespace(mode="content", limit=limite, dry_run=dry_run)
            auditor.run(args)

        elif op == "43":
            log("Reparando publicações com dados ruins…")
            repair.run()

        elif op == "44":
            print("""
Tipo de reset:

sinopse → reseta sinopse + status_publish (re-rodar steps 11 → 20 → 21)
capa    → reseta capa + status_publish    (re-rodar steps 12 → 20 → 21)
ambos   → ambos acima
""")
            reset_type = input_safe("Reset type [sinopse/capa/ambos]: ").strip().lower()
            if reset_type not in ("sinopse", "capa", "ambos"):
                print("Tipo inválido. Use: sinopse | capa | ambos\n")
            else:
                print("Digite os slugs, um por linha. Linha vazia para encerrar:")
                slugs = []
                while True:
                    s = input_safe("Slug: ").strip()
                    if not s:
                        break
                    slugs.append(s)
                if slugs:
                    targeted_repair.run(slugs, reset_type)
                else:
                    print("Nenhum slug informado.\n")

        elif op == "45":
            dry_op  = input_safe("Dry-run? (s/N): ").strip().lower()
            dry_run = dry_op == "s"
            log(f"Aplicando blacklist (dry_run={dry_run})…")
            apply_blacklist.run(dry_run=dry_run)

        elif op == "46":
            try:
                limite_str = input_safe("Limite de livros (Enter = catálogo completo): ").strip()
                limite = int(limite_str) if limite_str else 0
            except ValueError:
                limite = 0
            fmt = input_safe("Formato? [json/csv] (padrão: json): ").strip().lower() or "json"
            if fmt not in ("json", "csv"):
                fmt = "json"
            descricao = str(limite) if limite else "catálogo completo"
            log(f"Exportando {descricao} livros para auditoria (formato={fmt})…")
            _export_for_audit.run(limit=limite, fmt=fmt)

        elif op == "47":
            log("Auditoria de integridade do pipeline (sem LLM)…")
            with StepRun("autopilot_audit", idioma=idioma):
                autopilot_audit.run()

        elif op == "48":
            dry_op  = input_safe("Dry-run? (s/N): ").strip().lower()
            dry_run = dry_op == "s"
            log(f"Auditando listas SEO (dry_run={dry_run})…")
            args = argparse.Namespace(mode="list", dry_run=dry_run)
            auditor.run(args)

        elif op == "49":
            log("Verificando autores publicados sem bio…")
            args = argparse.Namespace(mode="author-bios", dry_run=False)
            auditor.run(args)

        elif op == "50":
            print("""
Escopo da verificação de títulos:

all       → todos os livros (publicados + pipeline)
published → apenas publicados no Supabase
pipeline  → apenas ainda não publicados
""")
            scope = input_safe("Escopo [all/published/pipeline] (padrão: all): ").strip().lower()
            if scope not in ("all", "published", "pipeline"):
                scope = "all"

            try:
                limite = int(input_safe("Limite de livros (padrão: 50): ").strip() or "50")
            except ValueError:
                limite = 50

            dry_op  = input_safe("Dry-run? (s/N): ").strip().lower()
            dry_run = dry_op == "s"

            from core.markdown_executor import set_provider
            set_provider(escolher_provider())

            log(f"Verificando veracidade de títulos (scope={scope}, limit={limite}, dry_run={dry_run})…")
            args = argparse.Namespace(
                mode="title-verify", limit=limite, scope=scope, dry_run=dry_run
            )
            auditor.run(args)

        elif op == "51":
            log("Gerando relatório de consistência (consulta Supabase)…")
            out = consistency_check.run()
            if out:
                print(f"""
=== PRÓXIMO PASSO ===
Relatório gerado: {out.name}

Abra o Claude Code e execute:
  Leia agents/consistency_review/prompt.md e execute todas as instruções.

O agente irá ler o relatório e tomar ações corretivas automaticamente.
""")
            input_safe("\nPressione Enter para voltar ao menu…")

        elif op == "52":
            dry_op  = input_safe("Dry-run? (s/N): ").strip().lower()
            dry_run = dry_op == "s"
            log(f"Reprocessando títulos da blacklist (dry_run={dry_run})…")
            reprocess_blacklist.run(dry_run=dry_run)

        elif op == "53":
            dry_op  = input_safe("Dry-run? (s/N): ").strip().lower()
            dry_run = dry_op == "s"
            log(f"QA — passe de remediação (dry_run={dry_run})…")
            qa.run(mode="remediate", dry_run=dry_run)

        elif op == "54":
            log("Auditando capas (sem LLM)…")
            args = argparse.Namespace(mode="covers", dry_run=False)
            auditor.run(args)

        elif op == "55":
            log("Auditando classificação (sem LLM)…")
            args = argparse.Namespace(mode="classification", dry_run=False)
            auditor.run(args)

        elif op == "56":
            log("QA — Auditoria completa do site (sem LLM)…")
            qa.run(mode="audit", dry_run=False)

        elif op == "57":
            dry_op  = input_safe("Dry-run? (s/N): ").strip().lower()
            dry_run = dry_op == "s"
            log(f"QA — passe completo (auditoria + remediação, dry_run={dry_run})…")
            qa.run(mode="full", dry_run=dry_run)

        elif op == "58":
            log("QA — remediação de capas (publicados sem capa, com prioridade)…")
            qa.run(mode="remediate_covers")

        elif op == "59":
            log("QA — reconcile de sinopse (flag desync, sem LLM)…")
            qa.run(mode="reconcile_synopsis")

        elif op == "60":
            log("QA — marcar sinopses inválidas p/ regeneração (gatilho não-LLM)…")
            qa.run(mode="flag_synopsis_regen")

        elif op == "61":
            log("QA — ingerir relatórios de auditoria na fila de remediação (P1 → fila)…")
            qa.run(mode="ingest_audit")

        else:
            print("Opção inválida.\n")
            continue

        log(f"[PIPELINE] v{get_version()}")


def menu_banco():
    while True:
        print("""
--- BANCO DE DADOS ---

95 → Fazer backup do banco local
96 → Restaurar banco de backup
97 → Recuperar banco do Supabase + backup

V  → Voltar
""")
        op = input_safe("Opção: ")

        if op.upper() == "V":
            break

        elif op == "95":
            log("Fazendo backup do banco local…")
            db_backup.run()

        elif op == "96":
            log("Restaurando banco de backup…")
            db_restore.run()

        elif op == "97":
            log("Recuperando banco do Supabase + backup local…")
            db_recover.run()

        else:
            print("Opção inválida.\n")
            continue

        log(f"[PIPELINE] v{get_version()}")


def menu_exports():
    while True:
        print("""
--- EXPORTS ---

91 → Export Site Bootstrap
92 → Export Pipeline Summary
93 → Export Database Transcript
94 → Export Project Tree (JSON)

V  → Voltar
""")
        op = input_safe("Opção: ")

        if op.upper() == "V":
            break

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
# GARGALO PLAN (opção G)
# =========================

def _run_gargalo(idioma: str):
    """
    Opção G — Orquestrador único (WS6, passe único + relatório):
      1. reclaim de estados presos
      2. Plano priorizado (exibido + salvo em data/gargalo_plan.json)
      3. Fase LLM priorizada (WS1) — opcional, consome a sessão PRO
      4. QA / remediação (WS4/WS5): aplica blacklist + reprocessa recuperáveis
      5. Steps de auditoria auto-executáveis
      6. Autopilot A — se a fase LLM parou por limite de sessão, roda até
         RESTAURAR a quota (drena/publica não-LLM enquanto aguarda o reset) e
         então faz UM retry da fase LLM; caso contrário, apenas exaure o não-LLM.
      7. Relatório: janela de sessão PRO (WS7) + backlog restante

    A fase LLM em si é passe único (não aguarda reset dentro do orquestrador).
    O retry pós-fallback aproveita que o trabalho não-LLM costuma cobrir o
    cooldown de ~5h — a espera vira trabalho útil e a quota tende a voltar.
    """
    log("[G] Analisando gargalos e construindo plano de ataque…")

    from steps import reclaim
    reclaim.run()

    conn_g = get_conn()
    plan   = pipeline_status.build_gargalo_plan(conn_g, idioma)
    conn_g.close()

    # ── Exibe o plano ─────────────────────────────────────────
    sep = "─" * 62

    print()
    print("=" * 62)
    print("  PLANO DE ATAQUE — ORDEM REAL DE EXECUÇÃO")
    print("=" * 62)

    # A execução do G é uma sequência fixa por FASES (LLM → QA → auditorias →
    # Autopilot A), NÃO a ordem 'order' do plano. O display abaixo espelha o que
    # realmente roda. Classificamos os steps do plano nesses grupos:
    auto_steps     = []    # auditorias/consistência auto-executáveis (fase 3)
    pipeline_steps = []    # gargalos não-LLM — cobertos pelo Autopilot A (fase 4)
    info_steps     = []    # manuais / LLM informativos (NÃO auto)
    blacklist_pend = None  # entrada de blacklist — coberta pela fase QA (não duplicar)

    for s in plan["steps"]:
        t = s["type"]
        if t == "autopilot":
            continue                       # fase final fixa, exibida abaixo
        if not s.get("auto"):
            info_steps.append(s)
        elif t == "pipeline":
            pipeline_steps.append(s)
        elif s.get("key") == "apply_blacklist":
            blacklist_pend = s             # a fase QA já aplica a blacklist
        else:
            auto_steps.append(s)

    def _pend(s):
        return f"  ({s['pending']:,} pendentes)" if s.get("pending") else ""

    n = 0
    # Fase 1 — geração LLM (condicional)
    n += 1
    print(f"\n  {n}. [LLM ⚠     ] Fase de geração LLM (sinopses/categorias)")
    print(f"      !  Condicional: só se o claude CLI existir e você confirmar — consome a sessão PRO")

    # Fase 2 — QA / remediação (sempre)
    n += 1
    bl_txt = (f" ({blacklist_pend['pending']:,} entradas)"
              if blacklist_pend and blacklist_pend.get("pending") else "")
    print(f"\n  {n}. [QA        ] Remediação não-LLM: aplica blacklist{bl_txt} + reprocessa recuperáveis")

    # Fase 3 — auditorias auto-executáveis
    for s in auto_steps:
        n += 1
        print(f"\n  {n}. [AUDITORIA ] {s['label']}")
        print(f"      →  {s['reason']}{_pend(s)}")

    # Fase 4 — Autopilot A (cobre os gargalos de pipeline)
    n += 1
    print(f"\n  {n}. [AUTOPILOT ] Autopilot A — drena todos os steps não-LLM até exaurir")
    if pipeline_steps:
        print(f"      →  cobre os gargalos de pipeline:")
        for s in pipeline_steps:
            print(f"           • {s['label']}{_pend(s)}")

    # Manuais / LLM — NÃO executados automaticamente pelo G
    if info_steps:
        print(f"\n  {sep}")
        print(f"  NÃO executados automaticamente (rode manualmente):")
        for s in info_steps:
            print(f"      · [{s['type']}] {s['label']}{_pend(s)} — {s['reason']}")

    print()
    print(f"  {sep}")
    print(f"  Plano salvo em: scripts/data/gargalo_plan.json")
    print(f"  Fases automáticas: LLM (opcional) → QA → "
          f"{len(auto_steps)} auditoria(s) → Autopilot A")
    print()

    # Execução automática — sem confirmações: plano e fase LLM assumidos como SIM.
    log("[G] Executando o plano automaticamente (sem confirmação).")

    # Gatilho não-LLM: marca sinopses concluídas mas inválidas (placeholder/
    # heading/curta) como status_synopsis=0 ANTES da fase LLM, para o
    # orquestrador as regenerar neste mesmo passe.
    log("[G] ── Gatilho: marcar sinopses inválidas p/ regeneração ──")
    try:
        qa.run(mode="flag_synopsis_regen", dry_run=False)
    except Exception as e_sr:
        log(f"[G] AVISO: gatilho de regeneração de sinopse falhou: {e_sr}")

    # ── FASE LLM priorizada (WS1) — consome a sessão PRO ──
    from core.claude_runner import claude_available
    llm_limited = False   # True se a fase LLM parou por limite de sessão (habilita retry pós-fallback)
    if claude_available():
        log("[G] ── Fase LLM priorizada (orquestrador) ──")
        try:
            # Passe único: ao esgotar a sessão, o orquestrador roda o
            # Autopilot A (fallback) e DEVOLVE o controle ao G (não aguarda
            # o reset). O G então faz QA + Autopilot A + relatório.
            llm_limited = bool(llm_orchestrator.run(idioma, wait_for_reset=False))
        except KeyboardInterrupt:
            log("[G] Fase LLM interrompida pelo usuário.")
        except Exception as e_llm:
            log(f"[G] AVISO: fase LLM retornou com exceção: {e_llm}")
    else:
        log("[G] claude CLI não encontrado — pulando fase LLM (segue só não-LLM).")

    # ── FASE QA / REMEDIAÇÃO (WS4/WS5, não-LLM) ──────────────────
    log("[G] ── QA / remediação (blacklist → reprocessamento) ──")
    try:
        qa.run(mode="remediate", dry_run=False)
    except Exception as e_qa:
        log(f"[G] AVISO: QA/remediação falhou: {e_qa}")

    # Remediação mecânica não-LLM dos fatores de qualidade (capas + reconcile
    # de sinopse) — deixa o dado limpo antes das auditorias e da publicação.
    log("[G] ── QA / remediação mecânica (capas + reconcile sinopse) ──")
    try:
        qa.run(mode="remediate_mechanical", dry_run=False)
    except Exception as e_qm:
        log(f"[G] AVISO: remediação mecânica falhou: {e_qm}")

    # Reparo de ofertas (reusa steps existentes 27/28, não-LLM): corrige URLs
    # afiliadas no SQLite (idempotente, local) e força republicação idempotente
    # das ofertas no Supabase. Fecha o fator OFERTA do loop sem código novo.
    log("[G] ── Reparo de ofertas (URLs afiliadas + republicar) ──")
    try:
        fix_affiliate_urls.run()
        publish_ofertas.run_repair()
    except Exception as e_of:
        log(f"[G] AVISO: reparo de ofertas falhou: {e_of}")

    # ── Executa steps auto-executáveis ────────────────────────
    for step in auto_steps:
        key = step["key"]
        log(f"[G] ── {step['label']} ──")
        try:
            if key == "autopilot_audit":
                with StepRun("autopilot_audit", idioma=idioma, invocado_por="gargalo"):
                    autopilot_audit.run()

            elif key == "audit_connectivity":
                args_g = argparse.Namespace(mode="connectivity", dry_run=False)
                auditor.run(args_g)

            elif key == "audit_list":
                args_g = argparse.Namespace(mode="list", dry_run=False)
                auditor.run(args_g)

            elif key == "audit_author_bios":
                args_g = argparse.Namespace(mode="author-bios", dry_run=False)
                auditor.run(args_g)

            elif key == "consistency_check":
                out = consistency_check.run()
                if out:
                    log(f"[G] Relatório gerado: {out.name}")
                    log("[G] Execute o agente consistency_review no Claude Code após o plano.")

            elif key == "apply_blacklist":
                log("[G] Aplicando blacklist.json…")
                with StepRun("apply_blacklist", idioma=idioma, invocado_por="gargalo"):
                    apply_blacklist.run(dry_run=False)

            else:
                log(f"[G] Step '{key}' não tem execução automática. Pule manualmente.")

        except KeyboardInterrupt:
            log("[G] Interrompido pelo usuário.")
            return
        except Exception as e_g:
            log(f"[G] ERRO em {step['label']}: {e_g}")

    # ── Autopilot A + retry LLM oportunista ───────────────────
    # manter_batch=False: G já faz a fase LLM via orquestrador; o top-up de
    # batch aqui só geraria status=3 preso (sem consumidor externo).
    log("[G] Todos os steps de auditoria/manutenção concluídos.")

    if llm_limited and claude_available():
        # Autopilot A ATÉ RESTAURAR A QUOTA LLM: em vez de exaurir uma única vez
        # e parar, o não-LLM segue drenando/publicando enquanto a sessão PRO
        # está em cooldown; assim que a quota reseta, dispara o retry da fase
        # LLM. A espera de até ~5h vira trabalho útil e o retry fica garantido
        # (não depende de o fallback ter, por acaso, durado mais que o cooldown).
        from core.claude_usage_tracker import session_window
        import time as _time
        log("[G] Iniciando Autopilot A até restaurar a quota LLM…")
        try:
            while True:
                autopilot.run(idioma, 100, manter_batch=False)   # exaure o não-LLM
                w = session_window()
                if not w.get("in_cooldown"):
                    break                                        # quota restaurada
                secs = max(0, int(w.get("seconds_until_reset", 0)))
                nap = min(300, secs)                             # re-checa a cada ≤5 min
                if nap <= 0:
                    break
                log(f"[G] Backlog não-LLM drenado; aguardando reset da sessão "
                    f"(~{secs // 60} min restantes)…")
                _time.sleep(nap)
        except KeyboardInterrupt:
            log("[G] Espera produtiva (Autopilot até restaurar quota) interrompida pelo usuário.")

        if not session_window().get("in_cooldown"):
            log("[G] ── Retry da fase LLM (quota restaurada) ──")
            try:
                llm_orchestrator.run(idioma, wait_for_reset=False)
            except KeyboardInterrupt:
                log("[G] Retry da fase LLM interrompido pelo usuário.")
            except Exception as e_retry:
                log(f"[G] AVISO: retry da fase LLM retornou com exceção: {e_retry}")
            # Publica o que o retry desbloqueou (idempotente; barato se nada pendente).
            try:
                autopilot.run(idioma, 100, manter_batch=False)
            except Exception as e_ap2:
                log(f"[G] AVISO: autopilot pós-retry falhou: {e_ap2}")
        else:
            log("[G] Retry da fase LLM pulado — quota ainda em cooldown (espera interrompida).")
    else:
        # LLM concluiu todo o trabalho (ou claude indisponível): só exaure o
        # não-LLM uma vez — não há quota a aguardar.
        log("[G] Iniciando Autopilot A até exaustão…")
        autopilot.run(idioma, 100, manter_batch=False)

    # ── Relatório final (WS6/WS7): janela de sessão + backlog ──
    _print_gargalo_report(idioma)

    log(f"[G] Passe concluído. v{get_version()}")


def _run_wait_then_gargalo(idioma: str):
    """Opção W: aguarda o reset da janela de sessão Claude PRO (se em cooldown)
    e então roda o G automaticamente. Se a sessão já está disponível, roda já."""
    from core.claude_usage_tracker import session_window

    w = session_window()
    if not w.get("in_cooldown"):
        log("[W] Sessão Claude disponível (sem cooldown) — iniciando G imediatamente.")
        _run_gargalo(idioma)
        return

    reset_at = w.get("reset_at") or "?"
    log(f"[W] Sessão Claude em cooldown — aguardando o reset (previsto {reset_at}). "
        f"Use Ctrl+C para cancelar.")
    try:
        while True:
            w = session_window()
            if not w.get("in_cooldown"):
                break
            secs = max(0, int(w.get("seconds_until_reset", 0)))
            if secs <= 0:
                break
            log(f"[W] Faltam ~{secs // 60} min para o reset da sessão…")
            time.sleep(min(secs, 300))  # acorda a cada ≤5 min para re-checar
    except KeyboardInterrupt:
        log("[W] Espera cancelada pelo usuário — não rodou o G.")
        return

    log("[W] Sessão reiniciada — iniciando G.")
    _run_gargalo(idioma)


def _print_gargalo_report(idioma: str):
    """Relatório de passe único: estado da janela de sessão PRO (WS7) e o
    backlog de conteúdo que ainda destrava publicação. NÃO aguarda reset —
    orienta a re-rodar G após o reset, se houver trabalho LLM pendente."""
    sep = "─" * 62
    print()
    print("=" * 62)
    print("  RELATÓRIO DO PASSE (G)")
    print("=" * 62)

    # Backlog de conteúdo (gargalo)
    syn = cat = bio = quar = 0
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM livros WHERE status_synopsis=0 AND status_review=1 AND is_book=1 AND idioma=?", (idioma,))
        syn = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM livros WHERE status_categorize=0 AND status_review=1")
        cat = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM autores WHERE descricao IS NULL")
        bio = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM livros WHERE COALESCE(qa_quarantine,0)=1")
        quar = cur.fetchone()[0]
        conn.close()
    except Exception as e:
        log(f"[G] (relatório) AVISO ao contar backlog: {e}")

    print(f"  Backlog de conteúdo (destrava publicação):")
    print(f"    Sinopses pendentes ({idioma}): {syn:,}")
    print(f"    Categorizações pendentes     : {cat:,}")
    print(f"    Bios de autores pendentes    : {bio:,}")
    print(f"    Em quarentena (QA, definitiva): {quar:,}")
    print(f"  {sep}")

    # Janela de sessão PRO (WS7)
    try:
        from core.claude_usage_tracker import session_window, SESSION_RESET_MINUTES
        win = session_window()
        print(f"  Sessão Claude PRO (janela {SESSION_RESET_MINUTES}min):")
        print(f"    Chamadas na janela atual: {win['session_calls']:,}")
        content_left = syn + cat
        if win["in_cooldown"]:
            secs = win["seconds_until_reset"]
            h, rem = divmod(secs, 3600)
            m = rem // 60
            falta = f"{h}h{m:02d}min" if h else f"{m}min"
            print(f"    ⚠  LIMITE ATINGIDO — reset em ~{falta}.")
            if content_left > 0:
                print(f"    → Ainda há {content_left:,} item(ns) de conteúdo LLM. "
                      f"Re-rode G (ou O) após o reset para continuar.")
        else:
            print("    ✓  Janela disponível — sem cooldown.")
            if content_left > 0:
                print(f"    → {content_left:,} item(ns) de conteúdo ainda pendente(s) — "
                      f"rode G com a fase LLM para avançar.")
    except Exception as e:
        log(f"[G] (relatório) AVISO ao ler janela de sessão: {e}")
    print("=" * 62)
    print()


# =========================
# MAIN LOOP
# =========================

def main():

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--lang", default="PT", choices=["PT", "EN", "ES", "IT"],
                        help="Idioma base (padrão: PT)")
    args, _ = parser.parse_known_args()
    idioma = args.lang

    # ── Status automático na abertura ───────────────────────────
    log(f"[PIPELINE] v{get_version()} | iniciando…")
    pipeline_status.run()
    _startup_op = input_safe("Enter para o menu  |  ou já digite a opção (G, A, S…): ").strip()

    while True:

        # Na primeira iteração usa a opção digitada no startup (se houver)
        if _startup_op:
            op        = _startup_op
            _startup_op = ""
        else:
            print("""
=== LIVRARIA ALEXANDRIA — INGEST PIPELINE ===

S  → Status do pipeline (atualizar)
G  → Atacar gargalos — executa o plano automaticamente (sem confirmação) → Autopilot A
W  → Esperar reset da sessão Claude PRO e então rodar o G automaticamente
A  → Autopilot — roda todos os steps (sem LLM) em loop até exaurir
I  → Ingestão Orientada — pipeline completo com LLM (seeds → publicação)
O  → LLM Autopilot — 7 agentes LLM em ciclo exaustivo (claude CLI local)
M  → Manutenção — preços, conectividade, listas, bios (sem LLM)
C  → Batch Autopilot (sinopse + categorias via Claude)
E  → Exports

--- SUBMENUS ---
1  → Ingestão
2  → Pré-processamento
3  → Geração de Conteúdo
4  → Publicação
5  → Auditoria e Monitoramento
6  → Banco de Dados

0  → Sair
""")
            op = input_safe("Opção: ")

        if op == "0":
            break

        elif op in ("s", "S"):
            pipeline_status.run()
            input_safe("\nPressione Enter para voltar ao menu…")

        elif op.upper() == "G":
            _run_gargalo(idioma)

        elif op.upper() == "W":
            _run_wait_then_gargalo(idioma)

        elif op.upper() == "A":
            log("Iniciando autopilot (sem LLM)...")
            autopilot.run(idioma, 100, manter_batch=True)

        elif op.upper() == "I":
            log(f"Iniciando Ingestão Orientada (idioma={idioma}, provider=claude)…")
            ingestao_orientada.run(idioma)

        elif op.upper() == "O":
            from core.claude_runner import claude_available
            if not claude_available():
                log("[LLM_ORCH] ERRO: claude CLI não encontrado no PATH.")
                log("[LLM_ORCH] Instale o Claude Code CLI e tente novamente.")
                log("[LLM_ORCH] Alternativa: use C (Batch manual).")
            else:
                log(f"Iniciando LLM Autopilot (1 livro/chamada, idioma={idioma})…")
                llm_orchestrator.run(idioma)

        elif op.upper() == "M":
            try:
                price_str = input_safe("Limite price monitor (Enter = 50): ").strip()
                price_limit = int(price_str) if price_str else 50
            except ValueError:
                price_limit = 50
            dry_op  = input_safe("Dry-run? (s/N): ").strip().lower()
            dry_run = dry_op == "s"
            log(f"Iniciando autopilot de manutenção (price_limit={price_limit}, dry_run={dry_run})…")
            autopilot_manutencao.run(price_limit=price_limit, dry_run=dry_run)

        elif op.upper() == "C":
            import glob as _glob
            import os as _os
            import re as _re

            _BATCH_DIR = _os.path.join("data", "batch")
            _NUM_PAT    = _re.compile(r"^(\d{3})_")

            def _count_outputs():
                return (
                    len(_glob.glob(_os.path.join(_BATCH_DIR, "*_synopsis_output.json"))) +
                    len(_glob.glob(_os.path.join(_BATCH_DIR, "*_categorize_output.json")))
                )

            def _count_input_batches():
                """Conta lotes distintos de input pendentes (pelo número NNN)."""
                nums = set()
                for fpath in (
                    _glob.glob(_os.path.join(_BATCH_DIR, "*_synopsis_input.json")) +
                    _glob.glob(_os.path.join(_BATCH_DIR, "*_categorize_input.json"))
                ):
                    m = _NUM_PAT.match(_os.path.basename(fpath))
                    if m:
                        nums.add(m.group(1))
                return len(nums)

            def _export_n_batches(n):
                """Exporta até N lotes. Interrompe se não houver mais pendentes."""
                exportados = 0
                for _ in range(n):
                    with StepRun("batch_export", idioma=idioma, pacote=25):
                        batch_export.run(idioma, 25)
                    exportados += 1
                log(f"[BATCH] {exportados} lote(s) exportado(s).")

            def _print_next_step_instructions():
                has_syn = bool(_glob.glob(_os.path.join(_BATCH_DIR, "*_synopsis_input.json")))
                has_cls = bool(_glob.glob(_os.path.join(_BATCH_DIR, "*_categorize_input.json")))
                n_lotes = _count_input_batches()
                lines = [
                    "",
                    "=== PRÓXIMO PASSO ===",
                    f"Lotes aguardando o agente: {n_lotes}",
                    "Abra o Claude Code e use o comando para o tipo desejado:",
                    "",
                ]
                if has_syn:
                    lines += [
                        "  SINOPSES:",
                        "    Leia agents/synopsis_batch/prompt.md e execute todas as instruções.",
                        "",
                    ]
                if has_cls:
                    lines += [
                        "  CATEGORIAS:",
                        "    Leia agents/classify_batch/prompt.md e execute todas as instruções.",
                        "",
                    ]
                lines += [
                    "Cada execução processa UM lote e arquiva o input.",
                    "Repita para esgotar todos os lotes pendentes.",
                    "Depois volte aqui e pressione C → 1 para importar.",
                    "",
                ]
                print("\n".join(lines))

            # ── Status atual ──────────────────────────────────────────────
            n_outputs     = _count_outputs()
            n_input_lotes = _count_input_batches()
            n_syn_out = len(_glob.glob(_os.path.join(_BATCH_DIR, "*_synopsis_output.json")))
            n_cat_out = len(_glob.glob(_os.path.join(_BATCH_DIR, "*_categorize_output.json")))

            print(f"""
=== BATCH ===

  Lotes de input pendentes : {n_input_lotes}
  Outputs prontos p/ import: {n_syn_out} sinopse(s), {n_cat_out} categoria(s)

1 → Importar TODOS os resultados pendentes → SQLite
    {"(nenhum output disponível)" if n_outputs == 0 else f"({n_syn_out} sinopses + {n_cat_out} categorias)"}
2 → Exportar 1 lote
3 → Exportar 10 lotes simultâneos
4 → Ver instruções para o agente Batch
""")
            sub = input_safe("Opção: ")

            if sub == "1":
                if n_outputs == 0:
                    print("Nenhum output disponível para importar.\n")
                else:
                    log("Importando resultados do Batch…")
                    with StepRun("batch_import", idioma=idioma):
                        batch_import.run()

            elif sub == "2":
                log("Exportando 1 lote para Batch…")
                _export_n_batches(1)
                _print_next_step_instructions()

            elif sub == "3":
                log("Exportando 10 lotes para Batch…")
                _export_n_batches(10)
                _print_next_step_instructions()

            elif sub == "4":
                _print_next_step_instructions()

            else:
                print("Opção inválida.\n")

        elif op.upper() == "E":
            menu_exports()

        elif op == "1":
            menu_ingestao(idioma)

        elif op == "2":
            menu_preprocessamento(idioma)

        elif op == "3":
            menu_geracao_conteudo(idioma)

        elif op == "4":
            menu_publicacao(idioma)

        elif op == "5":
            menu_auditoria(idioma)

        elif op == "6":
            menu_banco()

        else:
            print("Opção inválida.\n")
            continue

        log(f"[PIPELINE] v{get_version()}")


# =========================
# BOOTSTRAP
# =========================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Rede de segurança final: qualquer Ctrl+C não tratado por um submenu
        # específico cai aqui — encerra sem traceback bruto.
        print("\n[PIPELINE] Encerrado pelo usuário (Ctrl+C).")
        sys.exit(0)
