# ============================================================
# INGESTÃO ORIENTADA — Opção I
# Livraria Alexandria
#
# Pipeline orientado a seeds, um de cada vez:
#
#   1. Re-ingestão: reseta steps falhos de livros QG-rejeitados
#      → sinopse, categorias, capa, oferta (por motivo)
#   2. Flush: processa qualquer pendência anterior ao loop de seeds
#      (modo per-livro para LLM se houver pendências)
#   3. Loop de seeds (menor número primeiro):
#      a. Importa um seed → obtém lista de book_ids inseridos
#      b. Batch não-LLM: slugify → dedup → enrich → resolver → scraper
#         → review → capas   (processa todos os títulos do seed em lote)
#      c. Per-livro LLM: para CADA título individualmente:
#         categorize → synopsis → QG → publicar livro
#      d. Publicação em lote: autores / cats / ofertas / listas
#      e. Move o seed para ingested_seeds/ e avança para o próximo
#
# Stop conditions:
#   - Todos os seeds processados
#   - Limite de sessão do Claude CLI atingido
#      → migra automaticamente para Autopilot (Opção A, sem LLM)
#   - Ctrl+C
#
# Tabela seed_queue (db.py):
#   Rastreia lifecycle dos seeds: pending → processing → done | failed
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

# Marcadores de limite de quota/sessão — Gemini e Claude
LLM_LIMIT_MARKERS = {
    "GEMINI_DAILY_LIMIT_REACHED",
    "CLAUDE_SESSION_LIMIT_REACHED",
}


def _is_llm_limit(e: Exception) -> bool:
    msg = str(e)
    return any(marker in msg for marker in LLM_LIMIT_MARKERS)


# =========================
# STEPS NÃO-LLM (batch)
# =========================

def _build_nonllm_steps(idioma: str) -> list:
    """Steps rápidos (CPU/banco/HTTP) sem LLM — executados em lote."""
    return [
        ("5  Slugs",             lambda p: slugify.run(idioma, p),                   PACOTE_BASE),
        ("6  Slugs Autores",     lambda p: slugify_autores.run(p),                   PACOTE_BASE),
        ("7  Dedup Autores",     lambda p: dedup_autores.run(),                      PACOTE_BASE),
        ("8  Dedup (antecip.)",  lambda p: dedup.run(idioma, p),                     PACOTE_BASE),
        ("2  Enrich Desc",       lambda p: enrich_descricao.run(p),                  PACOTE_BASE),
        ("3  Resolver Ofertas",  lambda p: offer_resolver.run(idioma, p),            PACOTE_RESOLVE),
        ("4  Scraper",           lambda p: marketplace_scraper.run(idioma, p),       PACOTE_SCRAPER),
        ("9  Review",            lambda p: review.run(idioma, p),                    PACOTE_BASE),
        ("12 Capas",             lambda p: covers.run(idioma, p),                    PACOTE_BASE),
    ]


def _build_publication_steps(idioma: str) -> list:
    """Steps de publicação em lote — rodados ao final de cada seed."""
    return [
        ("15 Publicar Autores",  lambda p: publish_autores.run(p),   PACOTE_BASE),
        ("16 Publicar Cats",     lambda p: publish_categorias.run(),  PACOTE_BASE),
        ("17 Publicar Ofertas",  lambda p: publish_ofertas.run(p),    PACOTE_BASE),
        ("18 Listas SEO",        lambda p: list_composer.run(),       PACOTE_BASE),
        ("19 Publicar Listas",   lambda p: publish_listas.run(),      PACOTE_BASE),
    ]


# =========================
# PENDING
# =========================

def _count_pending_llm(conn, idioma: str) -> int:
    cur = conn.cursor()
    cur.execute("""
        SELECT
            (SELECT COUNT(*) FROM livros
             WHERE status_synopsis  = 0
               AND status_review    = 1
               AND is_book          = 1
               AND idioma           = ?) +
            (SELECT COUNT(*) FROM livros
             WHERE status_categorize = 0
               AND status_review     = 1
               AND idioma            = ?)
    """, (idioma, idioma))
    return cur.fetchone()[0]


def _count_total_pending(conn, idioma: str) -> int:
    return autopilot.count_pending(conn) + _count_pending_llm(conn, idioma)


def _book_is_ready_for_llm(conn, book_id: str) -> bool:
    """Retorna True se o livro está pronto para LLM (review feito, is_book=1)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM livros
        WHERE id = ? AND status_review = 1 AND is_book = 1
        LIMIT 1
    """, (book_id,))
    return cur.fetchone() is not None


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
# SEED QUEUE
# =========================

def _queue_seed(conn, filename: str) -> None:
    """Registra um seed na fila (idempotente — ignora se já existir)."""
    conn.execute("""
        INSERT OR IGNORE INTO seed_queue (filename, status, queued_at)
        VALUES (?, 'pending', CURRENT_TIMESTAMP)
    """, (filename,))
    conn.commit()


def _queue_start(conn, filename: str) -> None:
    conn.execute("""
        UPDATE seed_queue
        SET status = 'processing', started_at = CURRENT_TIMESTAMP
        WHERE filename = ?
    """, (filename,))
    conn.commit()


def _queue_done(conn, filename: str, inserted: int, skipped: int) -> None:
    conn.execute("""
        UPDATE seed_queue
        SET status = 'done', completed_at = CURRENT_TIMESTAMP,
            inserted = ?, skipped = ?
        WHERE filename = ?
    """, (inserted, skipped, filename))
    conn.commit()


def _queue_failed(conn, filename: str, error_msg: str) -> None:
    conn.execute("""
        UPDATE seed_queue
        SET status = 'failed', completed_at = CURRENT_TIMESTAMP, error_msg = ?
        WHERE filename = ?
    """, (error_msg, filename))
    conn.commit()


# =========================
# BATCH NÃO-LLM PASS
# =========================

def _run_nonllm_batch(idioma: str, label: str) -> None:
    """Roda uma passagem dos steps não-LLM em lote (sem limit LLM possível).

    Processa todos os títulos pendentes de slugify → capas.
    Cicla em loop até não haver mais progresso.
    """
    STEPS = _build_nonllm_steps(idioma)

    conn = get_conn()
    pending_anterior = autopilot.count_pending(conn)
    conn.close()

    ciclos_com_erro_sem_progresso = 0
    ciclo = 0

    while True:
        ciclo += 1
        erros_no_ciclo = 0

        log(f"[INGEST_ORIENTADA][{label}][non-LLM] Ciclo {ciclo} | Pendente: {pending_anterior}")

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
        pending_atual = autopilot.count_pending(conn)
        conn.close()

        log(f"[INGEST_ORIENTADA][{label}][non-LLM] Fim ciclo {ciclo} | "
            f"Pendente: {pending_anterior} → {pending_atual}"
            + (f" | Erros: {erros_no_ciclo}" if erros_no_ciclo else ""))

        if pending_atual == 0:
            log(f"[INGEST_ORIENTADA][{label}][non-LLM] Exaurido.")
            break

        if pending_atual >= pending_anterior:
            if erros_no_ciclo > 0:
                ciclos_com_erro_sem_progresso += 1
                if ciclos_com_erro_sem_progresso >= MAX_CICLOS_COM_ERRO:
                    log("[INGEST_ORIENTADA][non-LLM] Limite de ciclos com erro atingido.")
                    break
            else:
                ciclos_com_erro_sem_progresso = 0
                log(f"[INGEST_ORIENTADA][{label}][non-LLM] Sem progresso — avançando para LLM.")
                break
        else:
            ciclos_com_erro_sem_progresso = 0
            pending_anterior = pending_atual


# =========================
# PER-LIVRO LLM
# =========================

def _process_book_llm(idioma: str, book_id: str) -> bool:
    """Processa UM livro individualmente pelos steps LLM + QG + publicação.

    Fluxo: categorize → synopsis → quality_gate → publicar livro

    Retorna True se o limite LLM foi atingido (pipeline deve parar).
    """
    # Categorize
    log(f"[INGEST_ORIENTADA][per-livro] Categorize → {book_id}")
    try:
        with StepRun("10 Categorize (LLM)", idioma=idioma, pacote=1,
                     invocado_por="ingestao_orientada"):
            categorize.run(idioma, 1, book_ids=[book_id])
    except RuntimeError as e:
        if _is_llm_limit(e):
            log(f"[INGEST_ORIENTADA] ⚠️ Limite LLM atingido na categorização.")
            return True
        log(f"[INGEST_ORIENTADA] ERRO Categorize [{book_id}]: {e}")
    except Exception as e:
        log(f"[INGEST_ORIENTADA] ERRO Categorize [{book_id}]: {e}")

    # Synopsis
    log(f"[INGEST_ORIENTADA][per-livro] Synopsis → {book_id}")
    try:
        with StepRun("11 Synopsis (LLM)", idioma=idioma, pacote=1,
                     invocado_por="ingestao_orientada"):
            synopsis.run(idioma, 1, book_ids=[book_id])
    except RuntimeError as e:
        if _is_llm_limit(e):
            log(f"[INGEST_ORIENTADA] ⚠️ Limite LLM atingido na sinopse.")
            return True
        log(f"[INGEST_ORIENTADA] ERRO Synopsis [{book_id}]: {e}")
    except Exception as e:
        log(f"[INGEST_ORIENTADA] ERRO Synopsis [{book_id}]: {e}")

    # Quality Gate — avalia publishability deste livro (escopo: apenas este book_id)
    log(f"[INGEST_ORIENTADA][per-livro] Quality Gate → {book_id}")
    try:
        with StepRun("13 Quality Gate", idioma=idioma, pacote=1,
                     invocado_por="ingestao_orientada"):
            quality_gate.evaluate_quality(idioma, 1, book_ids=[book_id])
    except Exception as e:
        log(f"[INGEST_ORIENTADA] ERRO Quality Gate [{book_id}]: {e}")

    # Publicar livro (se aprovado pelo QG) — escopo: apenas este book_id
    log(f"[INGEST_ORIENTADA][per-livro] Publicar → {book_id}")
    try:
        with StepRun("14 Publicar Livros", idioma=idioma, pacote=1,
                     invocado_por="ingestao_orientada"):
            publish.run(idioma, 1, book_ids=[book_id])
    except Exception as e:
        log(f"[INGEST_ORIENTADA] ERRO Publicar [{book_id}]: {e}")

    return False


def _run_llm_per_book(idioma: str, book_ids: list, label: str) -> bool:
    """Itera sobre book_ids processando cada um individualmente pelos steps LLM.

    Retorna True se o limite LLM foi atingido.
    """
    conn = get_conn()
    # Filtra apenas livros que passaram pelo review (prontos para LLM)
    ids_prontos = [bid for bid in book_ids if _book_is_ready_for_llm(conn, bid)]
    conn.close()

    total = len(ids_prontos)
    log(f"[INGEST_ORIENTADA][{label}] Per-livro LLM: {total} título(s) prontos.")

    for i, book_id in enumerate(ids_prontos, 1):
        log(f"[INGEST_ORIENTADA][{label}] ── Livro {i}/{total}: {book_id} ──")
        limit_hit = _process_book_llm(idioma, book_id)
        if limit_hit:
            return True

    return False


# =========================
# PUBLICATION BATCH
# =========================

def _run_publication_batch(idioma: str, label: str) -> None:
    """Roda os steps de publicação em lote após o ciclo per-livro."""
    STEPS = _build_publication_steps(idioma)
    for nome, step_fn, pacote_step in STEPS:
        log(f"[INGEST_ORIENTADA][{label}] -- {nome} --")
        try:
            with StepRun(nome, idioma=idioma, pacote=pacote_step,
                         invocado_por="ingestao_orientada"):
                step_fn(pacote_step)
        except Exception as e:
            log(f"[INGEST_ORIENTADA] ERRO em {nome}: {e}")


# =========================
# MIGRATE TO AUTOPILOT
# =========================

def _migrate_to_autopilot(idioma: str) -> None:
    """Ativa o Autopilot (sem LLM) após esgotamento da cota LLM.

    Processa tudo o que é possível sem LLM: resolver ofertas,
    publicar livros já aprovados, gerar listas, etc.
    """
    log("[INGEST_ORIENTADA] ══════════════════════════════════════")
    log("[INGEST_ORIENTADA] Limite LLM atingido → migrando para Autopilot (sem LLM)")
    log("[INGEST_ORIENTADA] ══════════════════════════════════════")
    try:
        autopilot.run(idioma, PACOTE_BASE)
    except KeyboardInterrupt:
        log("[INGEST_ORIENTADA] Autopilot interrompido pelo usuário.")
    except Exception as e:
        log(f"[INGEST_ORIENTADA] Autopilot encerrou com erro: {e}")


# =========================
# FLUSH DE PENDÊNCIAS (Fase 1)
# =========================

def _run_flush(idioma: str) -> bool:
    """Processa pendências anteriores (antes do loop de seeds).

    Modo híbrido:
    - Batch não-LLM primeiro
    - Per-livro LLM para os livros já prontos
    - Publicação em lote

    Retorna True se o limite LLM foi atingido.
    """
    log("[INGEST_ORIENTADA][flush] Iniciando batch não-LLM...")
    _run_nonllm_batch(idioma, "flush")

    # Per-livro LLM: processa em lotes de PACOTE_LLM até exaurir todos os pendentes
    while True:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM livros
            WHERE (status_synopsis = 0 OR status_categorize = 0)
              AND status_review = 1
              AND is_book = 1
              AND idioma = ?
            ORDER BY priority_score DESC, created_at ASC
            LIMIT ?
        """, (idioma, PACOTE_LLM))
        pending_llm_ids = [r[0] for r in cur.fetchall()]
        conn.close()

        if not pending_llm_ids:
            break

        log(f"[INGEST_ORIENTADA][flush] Per-livro LLM: {len(pending_llm_ids)} livro(s).")
        limit_hit = _run_llm_per_book(idioma, pending_llm_ids, "flush")
        if limit_hit:
            return True

    _run_publication_batch(idioma, "flush")
    return False


# =========================
# SEED IMPORT (unitário)
# =========================

def _import_seed(filename: str, filepath: str) -> tuple:
    """Importa um único seed e o move para ingested_seeds/.

    Retorna (ok: bool, inserted_ids: list, inserted: int, skipped: int).
    Não marca seed_queue como 'done' — isso é responsabilidade do caller
    após a conclusão completa de todos os steps (non-LLM + LLM + publicação).
    """
    conn = offer_seed.get_conn()
    offer_seed.ensure_tables(conn)

    inserted, skipped, inserted_ids = offer_seed.process_file(conn, filename, filepath)

    if inserted is None:
        log(f"[INGEST_ORIENTADA] Seed {filename} ignorado (erro de leitura). "
            "Arquivo permanece em seeds/ para correção.")
        conn.close()
        return False, [], 0, 0

    offer_seed.mark_imported(conn, filename, inserted, skipped or 0)
    conn.close()

    offer_seed.move_to_ingested(filepath, filename)
    log(f"[INGEST_ORIENTADA] Seed {filename} importado: "
        f"{inserted} inserido(s) | {skipped} pulado(s) | "
        f"{len(inserted_ids)} IDs rastreados.")
    return True, inserted_ids or [], inserted, skipped or 0


# =========================
# RUN
# =========================

def run(idioma: str, provider: str = "claude"):
    """Autopilot orientado a seeds, com LLM incluído.

    Design per-título:
      1. Pré-processamento em lote (não-LLM): slugify → dedup → enrich →
         resolver → scraper → review → capas
      2. Para cada título individualmente: categorize → synopsis → QG → publish
      3. Publicação de metadados em lote: autores / cats / ofertas / listas

    Ao atingir o limite de sessão do Claude CLI:
      → migra automaticamente para Autopilot (Opção A, sem LLM)
      → processa o que resta sem LLM antes de encerrar
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
    pending_pre = _count_total_pending(conn, idioma)
    conn.close()

    if pending_pre > 0:
        log(f"[INGEST_ORIENTADA] ── Fase 1: Flush ({pending_pre} pendentes) ──")
        try:
            limit_hit = _run_flush(idioma)
        except KeyboardInterrupt:
            log("[INGEST_ORIENTADA] Interrompido pelo usuário (Fase 1).")
            return
        if limit_hit:
            log("[INGEST_ORIENTADA] Limite LLM atingido na Fase 1.")
            _migrate_to_autopilot(idioma)
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

    # Enfilera todos os seeds descobertos
    conn = get_conn()
    for filename, _ in seed_files:
        _queue_seed(conn, filename)
    conn.close()

    try:
        for idx, (filename, filepath) in enumerate(seed_files, 1):
            log(f"[INGEST_ORIENTADA] ── Seed {idx}/{len(seed_files)}: {filename} ──")

            # Marca seed como "em processamento"
            conn = get_conn()
            _queue_start(conn, filename)
            conn.close()

            ok, book_ids, seed_inserted, seed_skipped = _import_seed(filename, filepath)
            if not ok:
                conn = get_conn()
                _queue_failed(conn, filename, "erro de leitura do arquivo")
                conn.close()
                log(f"[INGEST_ORIENTADA] Seed {filename} ignorado. Próximo seed.")
                continue

            # ── Passo 2a: batch não-LLM ─────────────────────────
            log(f"[INGEST_ORIENTADA][{filename}] ── Batch não-LLM ──")
            _run_nonllm_batch(idioma, filename)

            # ── Passo 2b: per-livro LLM ──────────────────────────
            log(f"[INGEST_ORIENTADA][{filename}] ── Per-livro LLM ({len(book_ids)} títulos) ──")
            limit_hit = _run_llm_per_book(idioma, book_ids, filename)

            if limit_hit:
                log(f"[INGEST_ORIENTADA] Limite LLM atingido durante seed {filename}.")
                log("[INGEST_ORIENTADA] Seeds restantes serão processados na próxima execução.")
                # seed_queue permanece como 'processing' — autopilot retomará os livros já
                # inseridos no banco na próxima execução.
                _migrate_to_autopilot(idioma)
                return

            # ── Passo 2c: publicação em lote ─────────────────────
            log(f"[INGEST_ORIENTADA][{filename}] ── Publicação em lote ──")
            _run_publication_batch(idioma, filename)

            # Marca seed como concluído apenas após todos os steps completarem
            conn = get_conn()
            _queue_done(conn, filename, seed_inserted, seed_skipped)
            conn.close()

    except KeyboardInterrupt:
        log("[INGEST_ORIENTADA] Interrompido pelo usuário (Fase 2).")
        return

    log("[INGEST_ORIENTADA] ══════════════════════════════════════")
    log("[INGEST_ORIENTADA] Todos os seeds processados. Concluído.")
    log("[INGEST_ORIENTADA] ══════════════════════════════════════")
