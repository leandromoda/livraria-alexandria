# ============================================================
# INGESTÃO ORIENTADA — Opção I
# Livraria Alexandria
#
# Autopilot full-pipeline com LLM, orientado a seeds.
# Processa seeds pendentes E reprocessa títulos presos.
#
# Sequência por ciclo:
#   1  Import seeds
#   2  Enrich desc (Google Books)
#   3  Resolver Ofertas
#   4  Marketplace Scraper (capa + preço)
#   5  Slugs
#   6  Slugify Autores
#   7  Dedup Autores
#   8  Dedup
#   9  Review
#   10 Categorize (LLM)
#   11 Synopsis (LLM)
#   12 Capas
#   13 Quality Gate
#   14 Publicar Livros
#   15 Publicar Autores
#   16 Publicar Categorias
#   17 Publicar Ofertas
#   18 Listas SEO
#   19 Publicar Listas
#
# Re-ingestão: ao iniciar, reseta status_synopsis dos livros
# rejeitados pelo Quality Gate para forçar nova geração de
# sinopse. Livros aprovados (is_publishable=1) mas não
# publicados são capturados automaticamente pelo step 14.
# ============================================================

from core.db import get_conn
from core.logger import log
from core.markdown_executor import set_provider
from core.run_logger import StepRun

from steps import (
    offer_seed,
    enrich_descricao,
    offer_resolver,
    marketplace_scraper,
    slugify,
    slugify_autores,
    dedup_autores,
    dedup,
    review,
    categorize,
    synopsis,
    covers,
    quality_gate,
    publish,
    publish_autores,
    publish_categorias,
    publish_ofertas,
    list_composer,
    publish_listas,
    autopilot,
)


# =========================
# CONFIG
# =========================

PACOTE_BASE    = 100
PACOTE_SCRAPER = 20
PACOTE_RESOLVE = 50
PACOTE_LLM     = 50

MAX_CICLOS_COM_ERRO = 3


# =========================
# PENDING (inclui LLM)
# =========================

def _count_pending_llm(conn) -> int:
    cur = conn.cursor()
    cur.execute("""
        SELECT
            (SELECT COUNT(*) FROM livros
             WHERE status_synopsis  = 0
               AND status_review    = 1
               AND is_book          = 1) +
            (SELECT COUNT(*) FROM livros
             WHERE status_categorize = 0
               AND status_review     = 1)
    """)
    return cur.fetchone()[0]


def _count_total_pending(conn) -> int:
    return autopilot.count_pending(conn) + _count_pending_llm(conn)


# =========================
# RE-INGESTÃO
# =========================

def _reset_qg_rejected(conn) -> int:
    """Reseta status_synopsis de livros rejeitados pelo QG.

    Livros com sinopse gerada mas reprovados no QG ficam presos porque o
    QG não roda novamente sobre eles (is_publishable já é 0). Resetar
    status_synopsis=0 força nova geração antes de re-avaliação.
    """
    cur = conn.cursor()
    cur.execute("""
        UPDATE livros
        SET status_synopsis = 0,
            updated_at      = CURRENT_TIMESTAMP
        WHERE is_publishable  = 0
          AND status_synopsis = 1
          AND status_review   = 1
          AND is_book         = 1
    """)
    count = cur.rowcount
    conn.commit()
    return count


# =========================
# RUN
# =========================

def run(idioma: str, provider: str = "gemini"):
    """Autopilot full-pipeline (com LLM) orientado a seeds.

    Itera ciclos até pending == 0 ou ausência de progresso.
    LLM steps (categorize + synopsis) são executados inline.
    """
    set_provider(provider)

    log("[INGEST_ORIENTADA] Iniciando…")
    log(f"[INGEST_ORIENTADA] idioma={idioma} | provider={provider}")

    # Verificação de integridade do banco
    try:
        conn = get_conn()
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        if ic != "ok":
            log(f"[INGEST_ORIENTADA] ERRO CRÍTICO: banco corrompido (integrity_check={ic}).")
            log("[INGEST_ORIENTADA] Restaure o backup e tente novamente.")
            return
    except Exception as e:
        log(f"[INGEST_ORIENTADA] ERRO CRÍTICO: banco inacessível: {e}")
        return

    # Normaliza offer_status='active' → 1 uma vez antes de iniciar
    try:
        publish_ofertas.fix_offer_status()
    except Exception as e:
        log(f"[INGEST_ORIENTADA] AVISO: fix_offer_status falhou: {e}. Continuando.")

    # Re-ingestão: reseta livros QG-rejeitados (uma vez por run)
    conn = get_conn()
    resetados = _reset_qg_rejected(conn)
    conn.close()
    if resetados > 0:
        log(f"[INGEST_ORIENTADA] Re-ingestão: {resetados} livro(s) QG-rejeitados tiveram "
            f"status_synopsis resetado para nova tentativa.")

    conn = get_conn()
    pending_anterior = _count_total_pending(conn)
    conn.close()

    STEPS = [
        ("1  Seeds",             lambda p: offer_seed.run(),                          PACOTE_BASE),
        ("2  Enrich Desc",       lambda p: enrich_descricao.run(p),                   PACOTE_BASE),
        ("3  Resolver Ofertas",  lambda p: offer_resolver.run(idioma, p),             PACOTE_RESOLVE),
        ("4  Scraper",           lambda p: marketplace_scraper.run(idioma, p),        PACOTE_SCRAPER),
        ("5  Slugs",             lambda p: slugify.run(idioma, p),                    PACOTE_BASE),
        ("6  Slugs Autores",     lambda p: slugify_autores.run(p),                    PACOTE_BASE),
        ("7  Dedup Autores",     lambda p: dedup_autores.run(),                       PACOTE_BASE),
        ("8  Dedup",             lambda p: dedup.run(idioma, p),                      PACOTE_BASE),
        ("9  Review",            lambda p: review.run(idioma, p),                     PACOTE_BASE),
        ("10 Categorize (LLM)",  lambda p: categorize.run(idioma, p),                 PACOTE_LLM),
        ("11 Synopsis (LLM)",    lambda p: synopsis.run(idioma, p),                   PACOTE_LLM),
        ("12 Capas",             lambda p: covers.run(idioma, p),                     PACOTE_BASE),
        ("13 Quality Gate",      lambda p: quality_gate.evaluate_quality(idioma, p),  PACOTE_BASE),
        ("14 Publicar Livros",   lambda p: publish.run(idioma, p),                    PACOTE_BASE),
        ("15 Publicar Autores",  lambda p: publish_autores.run(p),                    PACOTE_BASE),
        ("16 Publicar Cats",     lambda p: publish_categorias.run(),                  PACOTE_BASE),
        ("17 Publicar Ofertas",  lambda p: publish_ofertas.run(p),                    PACOTE_BASE),
        ("18 Listas SEO",        lambda p: list_composer.run(),                       PACOTE_BASE),
        ("19 Publicar Listas",   lambda p: publish_listas.run(),                      PACOTE_BASE),
    ]

    ciclos_com_erro_sem_progresso = 0
    ciclo = 0

    try:
        while True:
            ciclo += 1
            erros_no_ciclo = 0

            log("=" * 52)
            log(f"[INGEST_ORIENTADA] Ciclo {ciclo} | Pendente: {pending_anterior}")
            log("=" * 52)

            for nome, step_fn, pacote_step in STEPS:
                log(f"[INGEST_ORIENTADA] -- {nome} (pacote={pacote_step}) --")
                try:
                    with StepRun(nome, idioma=idioma, pacote=pacote_step,
                                 invocado_por="ingestao_orientada"):
                        step_fn(pacote_step)
                except Exception as e:
                    log(f"[INGEST_ORIENTADA] ERRO em {nome}: {e}")
                    erros_no_ciclo += 1

            conn = get_conn()
            pending_atual = _count_total_pending(conn)
            conn.close()

            log(f"[INGEST_ORIENTADA] Fim ciclo {ciclo} | "
                f"Pendente: {pending_anterior} → {pending_atual}"
                + (f" | Erros: {erros_no_ciclo}" if erros_no_ciclo else ""))

            if pending_atual == 0:
                log("[INGEST_ORIENTADA] Pipeline exaurido. Ingestão orientada concluída.")
                break

            if pending_atual >= pending_anterior:
                if erros_no_ciclo > 0:
                    ciclos_com_erro_sem_progresso += 1
                    log(
                        f"[INGEST_ORIENTADA][⚠️ GUARDRAIL] Sem progresso com {erros_no_ciclo} "
                        f"erro(s) no ciclo. "
                        f"Consecutivos: {ciclos_com_erro_sem_progresso}/{MAX_CICLOS_COM_ERRO}."
                    )
                    if ciclos_com_erro_sem_progresso >= MAX_CICLOS_COM_ERRO:
                        log(f"[INGEST_ORIENTADA] Limite de {MAX_CICLOS_COM_ERRO} ciclos com erro "
                            f"atingido. Corrija os erros e re-execute.")
                        break
                else:
                    ciclos_com_erro_sem_progresso = 0
                    log("[INGEST_ORIENTADA] Sem progresso em ciclo limpo. "
                        "Pipeline bloqueado ou exaurido.")
                    log("[INGEST_ORIENTADA] Verifique o status e o limite diário do Gemini.")
                    break
            else:
                ciclos_com_erro_sem_progresso = 0
                pending_anterior = pending_atual

    except KeyboardInterrupt:
        log(f"[INGEST_ORIENTADA] Interrompido após ciclo {ciclo}.")

    log(f"[INGEST_ORIENTADA] Total de ciclos: {ciclo}")
