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
    """Conta trabalho pendente em todos os steps não-LLM do pipeline.

    Cada sub-query espelha a condição de seleção do step correspondente,
    garantindo que o autopilot só para quando não há NADA a fazer —
    não apenas quando os steps visíveis estão estagnados.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT
            -- Step 1: Seeds (importação — sem pendência rastreável por contagem)

            -- Step 3: Resolver Ofertas
            (SELECT COUNT(*) FROM livros
             WHERE lookup_query IS NOT NULL
               AND offer_url IS NULL
               AND (offer_status IS NULL OR offer_status = 0 OR offer_status = 'active')) +

            -- Step 4: Scraper Marketplace
            (SELECT COUNT(*) FROM livros
             WHERE status_enrich = 0
               AND offer_url IS NOT NULL
               AND offer_url != '') +

            -- Step 5: Slugs
            (SELECT COUNT(*) FROM livros WHERE status_slug = 0) +

            -- Step 8: Dedup (depende de slug)
            (SELECT COUNT(*) FROM livros WHERE status_dedup  = 0 AND status_slug  = 1) +

            -- Step 9: Review (depende de dedup)
            (SELECT COUNT(*) FROM livros WHERE status_review = 0 AND status_dedup = 1) +

            -- Step 12: Capas (depende de review)
            (SELECT COUNT(*) FROM livros
             WHERE status_cover = 0 AND status_review = 1 AND is_book = 1) +

            -- Step 14: Publicar Livros
            (SELECT COUNT(*) FROM livros WHERE is_publishable = 1 AND status_publish = 0) +

            -- Step 15: Publicar Autores
            (SELECT COUNT(*) FROM autores WHERE status_publish = 0
               AND id IN (SELECT autor_id FROM livros_autores
                          JOIN livros ON livros.id = livros_autores.livro_id
                          WHERE livros.status_publish = 1)) +

            -- Step 16: Publicar Categorias
            (SELECT COUNT(*) FROM livros
             WHERE status_publish = 1 AND status_publish_cat = 0) +

            -- Step 17: Publicar Ofertas
            (SELECT COUNT(*) FROM livros
             WHERE status_publish = 1 AND status_publish_oferta = 0
               AND offer_url IS NOT NULL) +

            -- Step 19: Publicar Listas
            (SELECT COUNT(*) FROM listas WHERE status_publish = 0)
    """)
    return cur.fetchone()[0]


# =========================
# RUN
# =========================

def run(idioma: str, pacote: int, manter_cowork: bool = False, cowork_target: int = 10):
    """Loop automático: roda sequência não-LLM até não haver mais progresso.

    Para quando:
    - pending == 0: pipeline completamente exaurido
    - pending não diminuiu em ciclo SEM erros: bloqueado aguardando LLM (10, 11)
    - Ctrl+C: interrompido pelo usuário

    Guardrail anti-interrupção precoce:
    - Se um step lança exceção, o ciclo é marcado como "com erro"
    - Ciclos com erro não disparam o stop de "Sem progresso" — o erro pode
      ter impedido o progresso, não o LLM
    - O stop definitivo só ocorre em ciclo limpo (sem erros) sem progresso
    - Válvula de segurança: MAX_CICLOS_COM_ERRO ciclos consecutivos com erro
      e sem progresso também encerram (evita loop infinito em falha permanente)

    Args:
        manter_cowork: Se True, exporta lotes Cowork ao final de cada ciclo
                       para manter `cowork_target` inputs disponíveis ao agente.
        cowork_target: Número de lotes a manter disponíveis (padrão: 10).
    """
    MAX_CICLOS_COM_ERRO = 3  # para após N ciclos consecutivos com erro sem progresso

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

    # Guardrail: ciclos consecutivos com erro e sem progresso (válvula de segurança)
    ciclos_com_erro_sem_progresso = 0

    ciclo = 0
    try:
        while True:
            ciclo += 1
            erros_no_ciclo = 0  # reset a cada ciclo

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
                    erros_no_ciclo += 1

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

            log(f"[AUTOPILOT] Fim ciclo {ciclo} | Pendente: {pending_anterior} -> {pending_atual}"
                + (f" | Erros no ciclo: {erros_no_ciclo}" if erros_no_ciclo else ""))

            # Top-up de lotes Cowork (se habilitado)
            if manter_cowork:
                _topup_cowork(idioma, cowork_target)

            if pending_atual == 0:
                log("[AUTOPILOT] Pipeline exaurido. Nada mais a processar.")
                log("[AUTOPILOT] Iniciando auditoria de integridade...")
                autopilot_audit.run()
                break

            if pending_atual >= pending_anterior:
                if erros_no_ciclo > 0:
                    # Sem progresso por erro de step — não é bloqueio de LLM
                    ciclos_com_erro_sem_progresso += 1
                    log(
                        f"[AUTOPILOT][⚠️ GUARDRAIL] Sem progresso, mas {erros_no_ciclo} step(s) falharam "
                        f"neste ciclo — o erro pode ter impedido o avanço (não o LLM). "
                        f"Ciclos consecutivos com erro sem progresso: "
                        f"{ciclos_com_erro_sem_progresso}/{MAX_CICLOS_COM_ERRO}."
                    )
                    if ciclos_com_erro_sem_progresso >= MAX_CICLOS_COM_ERRO:
                        log(
                            f"[AUTOPILOT] Limite de {MAX_CICLOS_COM_ERRO} ciclos consecutivos com erro "
                            f"atingido. Corrija os erros acima e re-execute o autopilot."
                        )
                        log("[AUTOPILOT] Iniciando auditoria de integridade...")
                        autopilot_audit.run()
                        break
                    # Continua para o próximo ciclo
                else:
                    # Ciclo limpo sem progresso → pipeline aguardando LLM
                    ciclos_com_erro_sem_progresso = 0
                    log("[AUTOPILOT] Sem progresso. Pipeline aguardando steps LLM (10, 11).")
                    log("[AUTOPILOT] Rode step 10 (Categorizar) e step 11 (Sinopses) e repita.")
                    log("[AUTOPILOT] Iniciando auditoria de integridade...")
                    autopilot_audit.run()
                    break
            else:
                ciclos_com_erro_sem_progresso = 0  # reset quando há progresso real
                pending_anterior = pending_atual

    except KeyboardInterrupt:
        log(f"[AUTOPILOT] Interrompido apos ciclo {ciclo}.")

    log(f"[AUTOPILOT] Total de ciclos: {ciclo}")
