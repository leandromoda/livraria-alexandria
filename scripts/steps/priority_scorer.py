# ============================================================
# PRIORITY SCORER
# Livraria Alexandria
#
# Recalcula priority_score (0–1000) para todos os livros.
# Chamado no início de cada ciclo do autopilot para garantir
# que steps com ORDER BY priority_score processem os livros
# mais relevantes primeiro.
#
# Critérios de pontuação:
#   +400  Já publicado (needs oferta, categoria, etc.)
#   +200  Tem sinopse gerada
#   +200  Tem offer_url (link afiliado disponível)
#   +100  Passou no review
#   + 50  Tem descrição (>50 chars)
#   + 30  Tem imagem
#   + 20  Tem ISBN
# ============================================================

from core.db import get_conn
from core.logger import log


def recalculate_all(conn=None) -> int:
    """Recalcula priority_score para todos os livros. Retorna total atualizado."""
    close = conn is None
    if conn is None:
        conn = get_conn()

    conn.execute("""
        UPDATE livros SET priority_score = (
            CASE WHEN status_publish   = 1 THEN 400 ELSE 0 END +
            CASE WHEN status_synopsis  = 1 THEN 200 ELSE 0 END +
            CASE WHEN offer_url IS NOT NULL THEN 200 ELSE 0 END +
            CASE WHEN status_review    = 1 THEN 100 ELSE 0 END +
            CASE WHEN descricao IS NOT NULL AND length(descricao) > 50 THEN 50 ELSE 0 END +
            CASE WHEN imagem_url IS NOT NULL THEN 30 ELSE 0 END +
            CASE WHEN isbn IS NOT NULL THEN 20 ELSE 0 END
        )
    """)
    conn.commit()

    cur = conn.execute("SELECT COUNT(*) FROM livros")
    total = cur.fetchone()[0]

    if close:
        conn.close()

    return total


def run(idioma: str = None, pacote: int = None):
    """Interface padrão para uso no menu main.py."""
    total = recalculate_all()
    log(f"[PRIORITY] Scores recalculados para {total} livros")
