# ============================================================
# INGESTÃO ORIENTADA — Opção I
# Livraria Alexandria
#
# Pipeline orientado a seeds, um de cada vez:
#
#   1. Re-ingestão: reseta steps falhos de livros QG-rejeitados
#      → sinopse, categorias, capa, oferta (por motivo)
#   2. Flush: processa qualquer pendência anterior ao loop de seeds
#   3. Loop de seeds (menor número primeiro):
#      a. Importa um seed
#      b. Executa o pipeline completo até exaurir ou estagnar
#      c. Move o seed para ingested_seeds/
#      d. Avança para o próximo seed
#
# Ordem dos steps (dedup antecipado — antes do HTTP):
#   slugify → dedup → enrich → resolver → scraper
#   → review → categorize (LLM) → synopsis (LLM) → capas → QG
#   → publish livros / autores / cats / ofertas / listas
#
# Stop conditions:
#   - Todos os seeds de /seeds processados
#   - Limite diário do Gemini atingido (RuntimeError)
#   - Ctrl+C
# ============================================================

from core.db import get_conn
from core.logger import log
from core.markdown_executor import set_provider
from core.run_logger import StepRun

import steps.offer_seed as offer_seed

from steps import (
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

GEMINI_LIMIT_MARKER = "GEMINI_DAILY_LIMIT_REACHED"


# =========================
# STEPS (dedup antecipado)
# =========================

def _build_steps(idioma: str) -> list:
    """Retorna a sequência de steps na ordem otimizada.

    Dedup vem logo após slugify — antes de resolver e scraper — para
    eliminar duplicatas antes das chamadas HTTP mais custosas.
    """
    return [
        # Pré-processamento rápido (CPU/banco) — sem HTTP
        ("5  Slugs",             lambda p: slugify.run(idioma, p),                   PACOTE_BASE),
        ("6  Slugs Autores",     lambda p: slugify_autores.run(p),                   PACOTE_BASE),
        ("7  Dedup Autores",     lambda p: dedup_autores.run(),                      PACOTE_BASE),
        ("8  Dedup (antecip.)",  lambda p: dedup.run(idioma, p),                     PACOTE_BASE),
        # HTTP / APIs externas (apenas para livros não-duplicados)
        ("2  Enrich Desc",       lambda p: enrich_descricao.run(p),                  PACOTE_BASE),
        ("3  Resolver Ofertas",  lambda p: offer_resolver.run(idioma, p),            PACOTE_RESOLVE),
        ("4  Scraper",           lambda p: marketplace_scraper.run(idioma, p),       PACOTE_SCRAPER),
        # Editorial
        ("9  Review",            lambda p: review.run(idioma, p),                    PACOTE_BASE),
        # LLM
        ("10 Categorize (LLM)",  lambda p: categorize.run(idioma, p),                PACOTE_LLM),
        ("11 Synopsis (LLM)",    lambda p: synopsis.run(idioma, p),                  PACOTE_LLM),
        # Capas + Quality Gate
        ("12 Capas",             lambda p: covers.run(idioma, p),                    PACOTE_BASE),
        ("13 Quality Gate",      lambda p: quality_gate.evaluate_quality(idioma, p), PACOTE_BASE),
        # Publicação
        ("14 Publicar Livros",   lambda p: publish.run(idioma, p),                   PACOTE_BASE),
        ("15 Publicar Autores",  lambda p: publish_autores.run(p),                   PACOTE_BASE),
        ("16 Publicar Cats",     lambda p: publish_categorias.run(),                 PACOTE_BASE),
        ("17 Publicar Ofertas",  lambda p: publish_ofertas.run(p),                   PACOTE_BASE),
        ("18 Listas SEO",        lambda p: list_composer.run(),                      PACOTE_BASE),
        ("19 Publicar Listas",   lambda p: publish_listas.run(),                     PACOTE_BASE),
    ]


# =========================
# PENDING
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

def _reset_for_reingestion(conn) -> dict:
    """Reseta steps com falha para livros QG-rejeitados (por motivo).

    Sinopse curta/genérica → status_synopsis=0 (força nova geração)
    Categorias             → status_categorize=0 (força nova classificação)
    Capa pendente          → status_cover=0 (já deve estar 0; garante consistência)
    Oferta ausente         → offer_status='active' (permite nova tentativa do resolver)
    """
    cur = conn.cursor()
    results: dict = {}

    # Sinopse: estava "feita" mas reprovada pelo QG (curta ou genérica)
    cur.execute("""
        UPDATE livros
        SET status_synopsis = 0,
            updated_at      = CURRENT_TIMESTAMP
        WHERE is_publishable  = 0
          AND status_synopsis = 1
          AND status_review   = 1
          AND is_book         = 1
    """)
    results["sinopse"] = cur.rowcount

    # Categorias: permite nova classificação em caso de rejeição
    cur.execute("""
        UPDATE livros
        SET status_categorize = 0,
            updated_at        = CURRENT_TIMESTAMP
        WHERE is_publishable   = 0
          AND status_categorize = 1
          AND status_review    = 1
    """)
    results["categorias"] = cur.rowcount

    # Capa: garante que status_cover=0 para reprocessamento
    cur.execute("""
        UPDATE livros
        SET status_cover = 0,
            updated_at   = CURRENT_TIMESTAMP
        WHERE is_publishable = 0
          AND status_cover NOT IN (1, 2)
          AND status_review = 1
          AND is_book = 1
    """)
    results["capa"] = cur.rowcount

    # Oferta: reativa resolver para livros sem URL de afiliado
    cur.execute("""
        UPDATE livros
        SET offer_status = 'active',
            updated_at   = CURRENT_TIMESTAMP
        WHERE is_publishable = 0
          AND (offer_url IS NULL OR offer_url = '')
          AND status_review   = 1
    """)
    results["oferta"] = cur.rowcount

    conn.commit()
    return results


# =========================
# PIPELINE PASS
# =========================

def _run_pipeline(idioma: str, label: str) -> bool:
    """Executa o pipeline em loop até exaurir, estagnar ou atingir o limite Gemini.

    Retorna True se o limite diário do Gemini foi atingido.
    """
    STEPS = _build_steps(idioma)

    conn = get_conn()
    pending_anterior = _count_total_pending(conn)
    conn.close()

    ciclos_com_erro_sem_progresso = 0
    ciclo = 0

    while True:
        ciclo += 1
        erros_no_ciclo = 0
        gemini_limit = False

        log(f"[INGEST_ORIENTADA][{label}] Ciclo {ciclo} | Pendente: {pending_anterior}")

        for nome, step_fn, pacote_step in STEPS:
            log(f"[INGEST_ORIENTADA] -- {nome} (pacote={pacote_step}) --")
            try:
                with StepRun(nome, idioma=idioma, pacote=pacote_step,
                             invocado_por="ingestao_orientada"):
                    step_fn(pacote_step)
            except RuntimeError as e:
                if GEMINI_LIMIT_MARKER in str(e):
                    log(f"[INGEST_ORIENTADA] ⚠️ Limite diário do Gemini atingido em {nome}.")
                    gemini_limit = True
                    break
                log(f"[INGEST_ORIENTADA] ERRO em {nome}: {e}")
                erros_no_ciclo += 1
            except Exception as e:
                log(f"[INGEST_ORIENTADA] ERRO em {nome}: {e}")
                erros_no_ciclo += 1

        if gemini_limit:
            return True

        conn = get_conn()
        pending_atual = _count_total_pending(conn)
        conn.close()

        log(f"[INGEST_ORIENTADA][{label}] Fim ciclo {ciclo} | "
            f"Pendente: {pending_anterior} → {pending_atual}"
            + (f" | Erros: {erros_no_ciclo}" if erros_no_ciclo else ""))

        if pending_atual == 0:
            log(f"[INGEST_ORIENTADA][{label}] Pipeline exaurido.")
            break

        if pending_atual >= pending_anterior:
            if erros_no_ciclo > 0:
                ciclos_com_erro_sem_progresso += 1
                log(f"[INGEST_ORIENTADA][⚠️ GUARDRAIL] {ciclos_com_erro_sem_progresso}/"
                    f"{MAX_CICLOS_COM_ERRO} ciclos consecutivos com erro sem progresso.")
                if ciclos_com_erro_sem_progresso >= MAX_CICLOS_COM_ERRO:
                    log("[INGEST_ORIENTADA] Limite de ciclos com erro atingido. "
                        "Avançando para o próximo seed.")
                    break
            else:
                ciclos_com_erro_sem_progresso = 0
                log(f"[INGEST_ORIENTADA][{label}] Sem progresso em ciclo limpo. "
                    "Avançando para o próximo seed.")
                break
        else:
            ciclos_com_erro_sem_progresso = 0
            pending_anterior = pending_atual

    return False


# =========================
# SEED IMPORT (unitário)
# =========================

def _import_seed(filename: str, filepath: str) -> bool:
    """Importa um único seed e o move para ingested_seeds/.

    Retorna True se o arquivo foi importado com sucesso.
    """
    conn = offer_seed.get_conn()
    offer_seed.ensure_tables(conn)

    inserted, skipped = offer_seed.process_file(conn, filename, filepath)

    if inserted is None:
        log(f"[INGEST_ORIENTADA] Seed {filename} ignorado (erro de leitura). "
            "Arquivo permanece em seeds/ para correção.")
        conn.close()
        return False

    offer_seed.mark_imported(conn, filename, inserted, skipped or 0)
    conn.close()

    offer_seed.move_to_ingested(filepath, filename)
    log(f"[INGEST_ORIENTADA] Seed {filename} importado: "
        f"{inserted} inserido(s) | {skipped} pulado(s).")
    return True


# =========================
# RUN
# =========================

def run(idioma: str, provider: str = "gemini"):
    """Autopilot orientado a seeds, com LLM incluído.

    Processa seeds pendentes um a um (menor número primeiro).
    Entre cada seed executa o pipeline completo.
    Para quando todos os seeds forem processados ou o
    limite diário do Gemini for atingido.
    """
    set_provider(provider)

    log("[INGEST_ORIENTADA] ══════════════════════════════════════")
    log(f"[INGEST_ORIENTADA] Iniciando | idioma={idioma} | provider={provider}")
    log("[INGEST_ORIENTADA] ══════════════════════════════════════")

    # Verificação de integridade
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

    # Normaliza offer_status='active' → 1
    try:
        publish_ofertas.fix_offer_status()
    except Exception as e:
        log(f"[INGEST_ORIENTADA] AVISO: fix_offer_status falhou: {e}. Continuando.")

    # ─── FASE 0: Re-ingestão ─────────────────────────────────
    log("[INGEST_ORIENTADA] ── Fase 0: Re-ingestão ──")
    conn = get_conn()
    resets = _reset_for_reingestion(conn)
    conn.close()

    total_reset = sum(resets.values())
    if total_reset > 0:
        log(f"[INGEST_ORIENTADA] Resets aplicados: "
            f"sinopse={resets['sinopse']} | "
            f"categorias={resets['categorias']} | "
            f"capa={resets['capa']} | "
            f"oferta={resets['oferta']}")
    else:
        log("[INGEST_ORIENTADA] Nenhum livro QG-rejeitado para resetar.")

    # ─── FASE 1: Flush de pendências anteriores ───────────────
    conn = get_conn()
    pending_pre = _count_total_pending(conn)
    conn.close()

    if pending_pre > 0:
        log(f"[INGEST_ORIENTADA] ── Fase 1: Flush ({pending_pre} pendentes) ──")
        try:
            gemini_limit = _run_pipeline(idioma, "flush")
        except KeyboardInterrupt:
            log("[INGEST_ORIENTADA] Interrompido pelo usuário (Fase 1).")
            return
        if gemini_limit:
            log("[INGEST_ORIENTADA] Limite Gemini atingido na Fase 1. "
                "Retome amanhã para continuar.")
            return
    else:
        log("[INGEST_ORIENTADA] Fase 1: sem pendências anteriores. Pulando.")

    # ─── FASE 2: Loop de seeds ────────────────────────────────
    seed_files = offer_seed.discover_seed_files()

    if not seed_files:
        log("[INGEST_ORIENTADA] Nenhum seed pendente em data/seeds/.")
        log("[INGEST_ORIENTADA] Ingestão orientada concluída.")
        return

    log(f"[INGEST_ORIENTADA] ── Fase 2: {len(seed_files)} seed(s) pendente(s) ──")

    try:
        for idx, (filename, filepath) in enumerate(seed_files, 1):
            log(f"[INGEST_ORIENTADA] ── Seed {idx}/{len(seed_files)}: {filename} ──")

            ok = _import_seed(filename, filepath)
            if not ok:
                log(f"[INGEST_ORIENTADA] Seed {filename} ignorado. Próximo seed.")
                continue

            gemini_limit = _run_pipeline(idioma, filename)
            if gemini_limit:
                log("[INGEST_ORIENTADA] Limite Gemini atingido. "
                    "Seeds restantes serão processados na próxima execução.")
                return

    except KeyboardInterrupt:
        log("[INGEST_ORIENTADA] Interrompido pelo usuário (Fase 2).")
        return

    log("[INGEST_ORIENTADA] ══════════════════════════════════════")
    log("[INGEST_ORIENTADA] Todos os seeds processados. Concluído.")
    log("[INGEST_ORIENTADA] ══════════════════════════════════════")
