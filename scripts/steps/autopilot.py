# ============================================================
# AUTOPILOT — Pipeline automático (sem LLM)
# Livraria Alexandria
#
# Roda todos os steps não-LLM em sequência, em loop,
# até não haver mais progresso ("exaurir as possibilidades").
#
# Steps LLM (10-Categorizar, 11-Sinopses, 22-Auditoria) são
# sempre pulados. O pipeline para automaticamente quando a fila
# trava aguardando esses steps manuais.
#
# Opção manter_cowork: ao final de cada ciclo exporta lotes de
# input para o agente Cowork até atingir o target (padrão: 10).
# ============================================================

import glob as _glob
import os as _os
import re as _re

from core.db import get_conn
from core.logger import log
from core.run_logger import StepRun

from steps import (
    offer_seed,
    # enrich_descricao removido — coberto pelo Step 4 (Scraper)
    offer_resolver,
    priority_scorer,
    autopilot_audit,
    marketplace_scraper,
    slugify,
    slugify_autores,
    dedup_autores,
    dedup,
    review,
    covers,
    quality_gate,
    publish,
    publish_autores,
    publish_categorias,
    publish_ofertas,
    list_composer,
    publish_listas,
    cowork_export,
)


# =========================
# COWORK TOP-UP
# =========================

_COWORK_DIR = _os.path.join("data", "cowork")
_NUM_PAT    = _re.compile(r"^(\d{3})_")


def _count_input_batches() -> int:
    """Conta lotes distintos de input pendentes em data/cowork/ (pelo NNN)."""
    nums: set = set()
    for fpath in (
        _glob.glob(_os.path.join(_COWORK_DIR, "*_synopsis_input.json")) +
        _glob.glob(_os.path.join(_COWORK_DIR, "*_categorize_input.json"))
    ):
        m = _NUM_PAT.match(_os.path.basename(fpath))
        if m:
            nums.add(m.group(1))
    return len(nums)


def _topup_cowork(idioma: str, target: int = 10):
    """Exporta lotes de Cowork até atingir `target` inputs pendentes."""
    atual  = _count_input_batches()
    needed = max(0, target - atual)
    if needed == 0:
        log(f"[AUTOPILOT][COWORK] {atual} lote(s) pendente(s) — meta de {target} já atingida.")
        return
    log(f"[AUTOPILOT][COWORK] {atual} lote(s) pendente(s) — exportando {needed} para completar {target}.")
    exportados = 0
    for i in range(needed):
        try:
            with StepRun("cowork_export", idioma=idioma, pacote=25, invocado_por="autopilot"):
                cowork_export.run(idioma, 25)
            exportados += 1
        except Exception as e:
            log(f"[AUTOPILOT][COWORK] Erro ao exportar lote {i + 1}: {e}")
            break  # não tentar mais se falhou
    log(f"[AUTOPILOT][COWORK] {exportados} lote(s) exportado(s). Total pendente: {_count_input_batches()}.")


# =========================
# BATCH ADAPTATIVOS
# =========================

# Steps lentos (scraping/HTTP) usam batch menor que o base.
# Steps rápidos (CPU/banco) recebem o `pacote` sem modificação.
STEP_PACOTES = {
    "3  Resolver Ofertas": lambda p: min(p, 50),   # HTTP com retry — lento
    "4  Scraper":          lambda p: min(p, 20),   # scraping HTML — mais lento
    "12 Capas":            lambda p: min(p, 50),   # API externa — médio
}


# =========================
# PENDENTE
# =========================

def count_pending(conn) -> int:
    """Conta livros com trabalho pendente nas etapas não-LLM."""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            (SELECT COUNT(*) FROM livros WHERE status_slug    = 0) +
            (SELECT COUNT(*) FROM livros WHERE status_dedup   = 0 AND status_slug   = 1) +
            (SELECT COUNT(*) FROM livros WHERE status_review  = 0 AND status_dedup  = 1) +
            (SELECT COUNT(*) FROM livros WHERE status_cover   = 0 AND status_review = 1 AND is_book = 1) +
            (SELECT COUNT(*) FROM livros WHERE is_publishable = 1 AND status_publish       = 0) +
            (SELECT COUNT(*) FROM livros WHERE status_publish = 1 AND status_publish_oferta = 0
                                           AND offer_url IS NOT NULL)
    """)
    return cur.fetchone()[0]


# =========================
# RUN
# =========================

def run(idioma: str, pacote: int, manter_cowork: bool = False, cowork_target: int = 10):
    """Loop automático: roda sequência não-LLM até não haver mais progresso.

    Para quando:
    - pending == 0: pipeline completamente exaurido
    - pending não diminuiu: bloqueado aguardando LLM (steps 10, 11)
    - Ctrl+C: interrompido pelo usuário

    Args:
        manter_cowork: Se True, exporta lotes Cowork ao final de cada ciclo
                       para manter `cowork_target` inputs disponíveis ao agente.
        cowork_target: Número de lotes a manter disponíveis (padrão: 10).
    """

    # Normaliza offer_status='active' → 1 uma única vez
    publish_ofertas.fix_offer_status()

    # Top-up inicial de lotes Cowork (antes do primeiro ciclo)
    if manter_cowork:
        _topup_cowork(idioma, cowork_target)

    conn = get_conn()
    pending_anterior = count_pending(conn)
    conn.close()

    STEPS = [
        ("1  Seeds",             lambda p: offer_seed.run()),
        ("3  Resolver Ofertas",  lambda p: offer_resolver.run(idioma, p)),
        ("4  Scraper",           lambda p: marketplace_scraper.run(idioma, p)),
        ("5  Slugs",             lambda p: slugify.run(idioma, p)),
        ("6  Slugs Autores",     lambda p: slugify_autores.run()),
        ("7  Dedup Autores",     lambda p: dedup_autores.run()),
        ("8  Dedup",             lambda p: dedup.run(idioma, p)),
        ("9  Review",            lambda p: review.run(idioma, p)),
        ("12 Capas",             lambda p: covers.run(idioma, p)),
        ("13 Quality Gate",      lambda p: quality_gate.evaluate_quality(idioma, p)),
        ("14 Publicar Livros",   lambda p: publish.run(idioma, p)),
        ("15 Publicar Autores",  lambda p: publish_autores.run(p)),
        ("16 Publicar Cats",     lambda p: publish_categorias.run()),
        ("17 Publicar Ofertas",  lambda p: publish_ofertas.run(p)),
        ("18 Listas SEO",        lambda p: list_composer.run()),
        ("19 Publicar Listas",   lambda p: publish_listas.run()),
    ]

    # Trigger de falha: conta quantas vezes consecutivas cada step não gerou progresso
    FAILURE_THRESHOLD = 3
    step_sem_progresso: dict = {}

    ciclo = 0
    try:
        while True:
            ciclo += 1
            log("=" * 52)
            log(f"[AUTOPILOT] Ciclo {ciclo} | idioma={idioma} | pacote={pacote}")
            log(f"[AUTOPILOT] Pendente no inicio: {pending_anterior}")
            log("=" * 52)

            # Recalcula prioridades antes de processar os steps
            conn = get_conn()
            priority_scorer.recalculate_all(conn)
            conn.close()

            for nome, step_fn in STEPS:
                pacote_efetivo = STEP_PACOTES.get(nome, lambda p: p)(pacote)
                log(f"[AUTOPILOT] -- {nome} (pacote={pacote_efetivo}) --")

                conn = get_conn()
                pending_pre = count_pending(conn)
                conn.close()

                try:
                    with StepRun(nome, idioma=idioma, pacote=pacote_efetivo, invocado_por="autopilot"):
                        step_fn(pacote_efetivo)
                except Exception as e:
                    log(f"[AUTOPILOT] ERRO em {nome}: {e}")

                conn = get_conn()
                pending_pos = count_pending(conn)
                conn.close()

                if pending_pos >= pending_pre:
                    step_sem_progresso[nome] = step_sem_progresso.get(nome, 0) + 1
                    n = step_sem_progresso[nome]
                    if n >= FAILURE_THRESHOLD:
                        log(
                            f"[AUTOPILOT][⚠️ TRIGGER] Step '{nome}' executou {n}x consecutivas "
                            f"sem gerar progresso. Possível bloqueio ou step sem pendências."
                        )
                else:
                    step_sem_progresso[nome] = 0  # reset ao produzir progresso

            conn = get_conn()
            pending_atual = count_pending(conn)
            conn.close()

            log(f"[AUTOPILOT] Fim ciclo {ciclo} | Pendente: {pending_anterior} -> {pending_atual}")

            # Top-up de lotes Cowork (se habilitado)
            if manter_cowork:
                _topup_cowork(idioma, cowork_target)

            if pending_atual == 0:
                log("[AUTOPILOT] Pipeline exaurido. Nada mais a processar.")
                log("[AUTOPILOT] Iniciando auditoria de integridade...")
                autopilot_audit.run()
                break

            if pending_atual >= pending_anterior:
                log("[AUTOPILOT] Sem progresso. Pipeline aguardando steps LLM (10, 11).")
                log("[AUTOPILOT] Rode step 10 (Categorizar) e step 11 (Sinopses) e repita.")
                log("[AUTOPILOT] Iniciando auditoria de integridade...")
                autopilot_audit.run()
                break

            pending_anterior = pending_atual

    except KeyboardInterrupt:
        log(f"[AUTOPILOT] Interrompido apos ciclo {ciclo}.")

    log(f"[AUTOPILOT] Total de ciclos: {ciclo}")
