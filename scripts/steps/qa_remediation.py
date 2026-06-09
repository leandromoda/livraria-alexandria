# ============================================================
# QA — REMEDIAÇÃO (fecha o ciclo da auditoria do site)
# Livraria Alexandria
#
# Princípio (decisão de arquitetura): NÃO há scripts paralelos.
# A remediação reusa os STEPS PADRÃO via book_ids, dando PRIORIDADE
# aos títulos com defeito — eles já têm os demais requisitos de
# publicação, falta só corrigir o fator-causa.
#
# Fila: tabela qa_remediation (livro_id, factor, status, attempts...).
# Teto anti-thrash: após MAX_ATTEMPTS sem sucesso → quarentena
# (qa_quarantine=1) para não entrar em loop despublica↔regenera.
#
# Fatia inicial: CAPA (não-LLM, fix-in-place — NÃO despublica:
# o site lê o Supabase; marcar status_publish=0 só reenfileira o
# livro para o step de publicação padrão re-fazer o upsert da capa).
# ============================================================

from core.db import get_conn
from core.logger import log
from steps import covers, publish

FACTOR_CAPA = "capa"
MAX_ATTEMPTS = 3


def enqueue_covers(conn, source_report=None) -> tuple[int, int]:
    """Enfileira (status=pending) livros publicados sem capa.

    Idempotente: o índice parcial único (livro_id, factor) impede duplicar uma
    remediação ainda aberta. Retorna (novos_enfileirados, total_detectados).
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM livros
        WHERE status_publish = 1
          AND (imagem_url IS NULL OR imagem_url = '')
          AND COALESCE(qa_quarantine, 0) = 0
    """)
    ids = [r[0] for r in cur.fetchall()]
    novos = 0
    for lid in ids:
        try:
            cur.execute("""
                INSERT INTO qa_remediation (livro_id, factor, reason, status, source_report)
                VALUES (?, ?, ?, 'pending', ?)
            """, (lid, FACTOR_CAPA, "publicado sem capa", source_report))
            novos += 1
        except Exception:
            pass  # já há remediação aberta para (livro, capa)
    conn.commit()
    return novos, len(ids)


def drain_covers(conn, limit: int = 50) -> dict:
    """Reprocessa, COM PRIORIDADE, as capas pendentes (fix-in-place)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, livro_id FROM qa_remediation
        WHERE factor = ? AND status IN ('pending', 'reprocessing')
        ORDER BY attempts ASC, detected_at ASC
        LIMIT ?
    """, (FACTOR_CAPA, limit))
    fila = cur.fetchall()
    if not fila:
        return {"processados": 0, "corrigidos": 0, "quarentena": 0}

    rem_ids  = [r[0] for r in fila]
    book_ids = [r[1] for r in fila]

    # Reset da flag-causa → o step padrão de capas regenera. Marca a fila como
    # reprocessing e incrementa attempts (commit antes de chamar o step, que
    # abre conexão própria).
    qm = ",".join("?" * len(book_ids))
    cur.execute(f"UPDATE livros SET status_cover = 0 WHERE id IN ({qm})", tuple(book_ids))
    rm = ",".join("?" * len(rem_ids))
    cur.execute(
        f"""UPDATE qa_remediation
            SET status='reprocessing', attempts=attempts+1, last_attempt_at=CURRENT_TIMESTAMP
            WHERE id IN ({rm})""",
        tuple(rem_ids),
    )
    conn.commit()

    # Reuso dos STEPS PADRÃO, targeted nos ids (prioridade). idioma=None: o
    # alvo é explícito (book_ids), sem filtrar por idioma.
    covers.run(None, len(book_ids), book_ids=book_ids)
    # Propaga ao Supabase via o step de publicação padrão (upsert). Marca
    # status_publish=0 para o publish re-selecionar — o site permanece no ar
    # (lê o Supabase) até o upsert atualizar a capa.
    fixed_local = [lid for (_rid, lid) in fila
                   if (cur.execute("SELECT imagem_url FROM livros WHERE id=?", (lid,)).fetchone() or [None])[0]]
    if fixed_local:
        fm = ",".join("?" * len(fixed_local))
        cur.execute(f"UPDATE livros SET status_publish = 0 WHERE id IN ({fm}) AND status_publish = 1",
                    tuple(fixed_local))
        conn.commit()
        publish.run(None, len(fixed_local), book_ids=fixed_local)

    # Avalia o resultado final (capa presente + republicado).
    corrigidos = quarentena = 0
    for rem_id, lid in fila:
        row = cur.execute(
            "SELECT imagem_url, status_publish FROM livros WHERE id=?", (lid,)
        ).fetchone()
        tem_capa = bool(row and row[0])
        publicado = bool(row and row[1] == 1)
        if tem_capa and publicado:
            cur.execute("UPDATE qa_remediation SET status='fixed' WHERE id=?", (rem_id,))
            corrigidos += 1
        else:
            att = cur.execute("SELECT attempts FROM qa_remediation WHERE id=?", (rem_id,)).fetchone()[0]
            if att >= MAX_ATTEMPTS:
                cur.execute("UPDATE qa_remediation SET status='quarantined' WHERE id=?", (rem_id,))
                cur.execute("UPDATE livros SET qa_quarantine = 1 WHERE id=?", (lid,))
                quarentena += 1
            else:
                cur.execute("UPDATE qa_remediation SET status='pending' WHERE id=?", (rem_id,))
    conn.commit()
    return {"processados": len(fila), "corrigidos": corrigidos, "quarentena": quarentena}


def run_covers(limit: int = 50) -> dict:
    """Passe de remediação de CAPAS: enfileira + drena com prioridade."""
    conn = get_conn()
    try:
        novos, total = enqueue_covers(conn)
        log(f"[QA-REMEDIA][capa] enfileirados: {novos} (de {total} publicados sem capa)")
        res = drain_covers(conn, limit=limit)
        log(f"[QA-REMEDIA][capa] processados={res['processados']} "
            f"corrigidos={res['corrigidos']} quarentena={res['quarentena']}")
        return res
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="QA — remediação (fatia: capas)")
    p.add_argument("--limit", type=int, default=50)
    a = p.parse_args()
    run_covers(limit=a.limit)
