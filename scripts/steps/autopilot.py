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
# ============================================================

from core.db import get_conn
from core.logger import log

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
    covers,
    quality_gate,
    publish,
    publish_autores,
    publish_categorias,
    publish_ofertas,
    list_composer,
    publish_listas,
)


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

def run(idioma: str, pacote: int):
    """Loop automático: roda sequência não-LLM até não haver mais progresso.

    Para quando:
    - pending == 0: pipeline completamente exaurido
    - pending nao diminuiu: bloqueado aguardando LLM (steps 10, 11)
    - Ctrl+C: interrompido pelo usuário
    """

    # Normaliza offer_status='active' → 1 uma única vez
    publish_ofertas.fix_offer_status()

    conn = get_conn()
    pending_anterior = count_pending(conn)
    conn.close()

    STEPS = [
        ("1  Seeds",             lambda: offer_seed.run()),
        ("2  Enriquecer",        lambda: enrich_descricao.run(pacote)),
        ("3  Resolver Ofertas",  lambda: offer_resolver.run(idioma, pacote)),
        ("4  Scraper",           lambda: marketplace_scraper.run(idioma, pacote)),
        ("5  Slugs",             lambda: slugify.run(idioma, pacote)),
        ("6  Slugs Autores",     lambda: slugify_autores.run()),
        ("7  Dedup Autores",     lambda: dedup_autores.run()),
        ("8  Dedup",             lambda: dedup.run(idioma, pacote)),
        ("9  Review",            lambda: review.run(idioma, pacote)),
        ("12 Capas",             lambda: covers.run(idioma, pacote)),
        ("13 Quality Gate",      lambda: quality_gate.evaluate_quality(idioma, pacote)),
        ("14 Publicar Livros",   lambda: publish.run(idioma, pacote)),
        ("15 Publicar Autores",  lambda: publish_autores.run(pacote)),
        ("16 Publicar Cats",     lambda: publish_categorias.run()),
        ("17 Publicar Ofertas",  lambda: publish_ofertas.run(pacote)),
        ("18 Listas SEO",        lambda: list_composer.run()),
        ("19 Publicar Listas",   lambda: publish_listas.run()),
    ]

    ciclo = 0
    try:
        while True:
            ciclo += 1
            log("=" * 52)
            log(f"[AUTOPILOT] Ciclo {ciclo} | idioma={idioma} | pacote={pacote}")
            log(f"[AUTOPILOT] Pendente no inicio: {pending_anterior}")
            log("=" * 52)

            for nome, step_fn in STEPS:
                log(f"[AUTOPILOT] -- {nome} --")
                try:
                    step_fn()
                except Exception as e:
                    log(f"[AUTOPILOT] ERRO em {nome}: {e}")

            conn = get_conn()
            pending_atual = count_pending(conn)
            conn.close()

            log(f"[AUTOPILOT] Fim ciclo {ciclo} | Pendente: {pending_anterior} -> {pending_atual}")

            if pending_atual == 0:
                log("[AUTOPILOT] Pipeline exaurido. Nada mais a processar.")
                break

            if pending_atual >= pending_anterior:
                log("[AUTOPILOT] Sem progresso. Pipeline aguardando steps LLM (10, 11).")
                log("[AUTOPILOT] Rode step 10 (Categorizar) e step 11 (Sinopses) e repita.")
                break

            pending_anterior = pending_atual

    except KeyboardInterrupt:
        log(f"[AUTOPILOT] Interrompido apos ciclo {ciclo}.")

    log(f"[AUTOPILOT] Total de ciclos: {ciclo}")
