# ============================================================
# STEP — DEDUP AUTORES
# Livraria Alexandria
#
# Deduplicação de autores por similaridade de nome.
# Limiar: 0.92 (mesmo do dedup.py para livros).
#
# Estratégia:
#   - Ordena autores por nº de relações DESC (master = mais relações)
#   - Para cada autor ainda não processado, busca similares
#   - Redireciona livros_autores do dup → master
#   - Remove o dup do SQLite local
#   - Marca master com status_publish = 0 se tiver dup publicado
#     (force re-publish para garantir consistência no Supabase)
# ============================================================

import unicodedata
from difflib import SequenceMatcher

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

SIMILARITY_THRESHOLD = 0.92


# =========================
# FETCH
# =========================

def fetch_autores_com_contagem(conn):
    """Retorna todos os autores ordenados por nº de relações DESC."""

    cur = conn.cursor()

    cur.execute("""
        SELECT
            a.id,
            a.nome,
            a.slug,
            a.status_publish,
            COUNT(la.livro_id) AS num_livros
        FROM autores a
        LEFT JOIN livros_autores la ON la.autor_id = a.id
        GROUP BY a.id
        ORDER BY num_livros DESC, a.created_at ASC
    """)

    return cur.fetchall()


# =========================
# SIMILARITY
# =========================

def _norm(s):
    """Normaliza texto para comparação: NFKD → ASCII → minúsculas."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()


def similar(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


# =========================
# MERGE
# =========================

def merge_autores(conn, master, dup):
    """
    Redireciona todas as relações livros_autores de dup → master.
    Livros já linkados ao master são silenciosamente ignorados (INSERT OR IGNORE).
    Depois deleta o dup.
    Se o dup estava publicado e o master não, reseta status_publish do master
    para forçar re-publicação.
    """

    master_id      = master["id"]
    dup_id         = dup["id"]
    master_pub     = master["status_publish"]
    dup_pub        = dup["status_publish"]

    cur = conn.cursor()

    # Redireciona relações
    cur.execute("""
        SELECT livro_id FROM livros_autores
        WHERE autor_id = ?
    """, (dup_id,))

    livros = [r["livro_id"] for r in cur.fetchall()]

    for livro_id in livros:
        cur.execute("""
            INSERT OR IGNORE INTO livros_autores (livro_id, autor_id, created_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (livro_id, master_id))

    # Remove relações antigas e o dup
    cur.execute("DELETE FROM livros_autores WHERE autor_id = ?", (dup_id,))
    cur.execute("DELETE FROM autores WHERE id = ?", (dup_id,))

    # Se dup estava publicado mas master não, força re-publicação
    if dup_pub == 1 and master_pub == 0:
        cur.execute("""
            UPDATE autores
            SET status_publish = 0,
                updated_at     = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (master_id,))

    conn.commit()

    log(f"MERGE | '{dup['nome']}' ({dup_id[:8]}) → '{master['nome']}' ({master_id[:8]}) | {len(livros)} relação(ões) redirecionada(s)")


# =========================
# RUN
# =========================

def run():

    conn = get_conn()
    cur  = conn.cursor()

    rows = fetch_autores_com_contagem(conn)

    if not rows:
        log("[DEDUP_AUTORES] Nenhum autor encontrado.")
        conn.close()
        return

    total     = len(rows)
    removidos = 0
    merged_ids = set()  # IDs já removidos — não processar como master

    log(f"[DEDUP_AUTORES] Analisando {total} autores (limiar={SIMILARITY_THRESHOLD})…")

    for i, master in enumerate(rows):

        if master["id"] in merged_ids:
            continue

        # Compara com todos os autores subsequentes ainda não removidos
        for dup in rows[i + 1:]:

            if dup["id"] in merged_ids:
                continue

            if similar(master["nome"], dup["nome"]) >= SIMILARITY_THRESHOLD:
                merge_autores(conn, master, dup)
                merged_ids.add(dup["id"])
                removidos += 1

    conn.close()

    log(f"[DEDUP_AUTORES] Finalizado | Analisados: {total} | Removidos: {removidos}")
