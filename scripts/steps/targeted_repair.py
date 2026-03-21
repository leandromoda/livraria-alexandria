# ============================================================
# STEP 24 — TARGETED REPAIR
# Livraria Alexandria
#
# Reset de flags por lista de slugs fornecida manualmente.
# Útil para re-processar livros específicos detectados pelo
# audit (step 21/22) sem afetar o restante do pipeline.
#
# Após executar: re-rodar steps 11 (sinopses) e/ou 12 (capas),
#                depois 13 (quality gate) → 14 (publicar) → 17 (ofertas)
# ============================================================

from core.db import get_conn
from core.logger import log
from steps.repair import reset_synopsis, reset_cover


# =========================
# FETCH POR SLUG
# =========================

def fetch_by_slugs(conn, slugs):
    cur = conn.cursor()
    placeholders = ",".join("?" * len(slugs))
    cur.execute(f"""
        SELECT id, slug, titulo
        FROM livros
        WHERE slug IN ({placeholders})
    """, slugs)
    return cur.fetchall()


# =========================
# RUN
# =========================

def run(slugs: list, reset_type: str):
    """
    Reset direcionado por slug.

    Args:
        slugs:      lista de slugs a reparar
        reset_type: 'sinopse' | 'capa' | 'ambos'
    """
    if not slugs:
        log("[TARGETED_REPAIR] Nenhum slug fornecido.")
        return

    conn = get_conn()

    rows = fetch_by_slugs(conn, slugs)
    encontrados = {r[1]: r for r in rows}  # slug → (id, slug, titulo)

    nao_encontrados = [s for s in slugs if s not in encontrados]
    if nao_encontrados:
        for s in nao_encontrados:
            log(f"[TARGETED_REPAIR] WARNING — slug não encontrado: {s}")

    if not encontrados:
        log("[TARGETED_REPAIR] Nenhum livro encontrado para os slugs informados.")
        conn.close()
        return

    ids = [r[0] for r in encontrados.values()]

    log(f"[TARGETED_REPAIR] {len(ids)} livro(s) encontrado(s) para reset_type='{reset_type}'")
    for livro_id, slug, titulo in encontrados.values():
        log(f"  • {titulo}  ({slug})")

    if reset_type in ("sinopse", "ambos"):
        reset_synopsis(conn, ids)
        log(f"[TARGETED_REPAIR] sinopse: {len(ids)} livro(s) resetados → re-rodar step 11 → 13 → 14")

    if reset_type in ("capa", "ambos"):
        reset_cover(conn, ids)
        log(f"[TARGETED_REPAIR] capa: {len(ids)} livro(s) resetados → re-rodar step 12 → 13 → 14")

    conn.close()
    log(f"[TARGETED_REPAIR] Concluído | Resetados: {len(ids)} | Não encontrados: {len(nao_encontrados)}")
