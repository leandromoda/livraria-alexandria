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

    # Classifica cada livro após a geração de capa:
    #   - sem capa            → nenhuma fonte achou (retry → quarentena por tentativas)
    #   - capa + passa o gate → republicável (propaga ao Supabase via publish)
    #   - capa + falha o gate → bloqueado: defeito mais profundo (is_publishable /
    #     status_synopsis). NÃO mexe em status_publish (evita estrandar) e vai p/
    #     quarentena COM MOTIVO — é caso da próxima fatia (sinopse).
    publicaveis, bloqueados, sem_capa = [], [], []
    for rem_id, lid in fila:
        row = cur.execute(
            """SELECT imagem_url, is_publishable, status_synopsis,
                      length(COALESCE(sinopse, ''))
               FROM livros WHERE id=?""", (lid,)
        ).fetchone()
        if not (row and row[0]):
            sem_capa.append((rem_id, lid))
        elif row[1] == 1 and row[2] == 1 and (row[3] or 0) >= 80:
            publicaveis.append((rem_id, lid))
        else:
            bloqueados.append((rem_id, lid))

    # Propaga ao Supabase SÓ os republicáveis. status_publish=0 reenfileira para o
    # publish padrão (upsert) — o site permanece no ar (lê o Supabase). Restaura
    # pub=1 para qualquer um que o publish não tenha levado (robustez: nunca estranda).
    if publicaveis:
        ids = [lid for _, lid in publicaveis]
        ph = ",".join("?" * len(ids))
        cur.execute(f"UPDATE livros SET status_publish=0 WHERE id IN ({ph}) AND status_publish=1", tuple(ids))
        conn.commit()
        publish.run(None, len(ids), book_ids=ids)
        cur.execute(f"UPDATE livros SET status_publish=1 WHERE id IN ({ph}) AND status_publish=0", tuple(ids))
        conn.commit()

    corrigidos = bloqueados_n = quarentena = 0

    for rem_id, lid in publicaveis:
        row = cur.execute("SELECT imagem_url, status_publish FROM livros WHERE id=?", (lid,)).fetchone()
        if row and row[0] and row[1] == 1:
            cur.execute("UPDATE qa_remediation SET status='fixed' WHERE id=?", (rem_id,))
            corrigidos += 1
        else:
            cur.execute("UPDATE qa_remediation SET status='pending' WHERE id=?", (rem_id,))

    for rem_id, lid in bloqueados:
        cur.execute(
            "UPDATE qa_remediation SET status='quarantined', reason=? WHERE id=?",
            ("capa obtida; publish bloqueado (is_publishable/status_synopsis pendente) — fatia sinopse", rem_id),
        )
        cur.execute("UPDATE livros SET qa_quarantine=1 WHERE id=?", (lid,))
        bloqueados_n += 1

    for rem_id, lid in sem_capa:
        att = cur.execute("SELECT attempts FROM qa_remediation WHERE id=?", (rem_id,)).fetchone()[0]
        if att >= MAX_ATTEMPTS:
            cur.execute(
                "UPDATE qa_remediation SET status='quarantined', reason=? WHERE id=?",
                ("sem fonte de capa após múltiplas tentativas", rem_id),
            )
            cur.execute("UPDATE livros SET qa_quarantine=1 WHERE id=?", (lid,))
            quarentena += 1
        else:
            cur.execute("UPDATE qa_remediation SET status='pending' WHERE id=?", (rem_id,))

    conn.commit()
    return {"processados": len(fila), "corrigidos": corrigidos,
            "bloqueados": bloqueados_n, "quarentena": quarentena}


def run_covers(limit: int = 50) -> dict:
    """Passe de remediação de CAPAS: enfileira + drena com prioridade."""
    conn = get_conn()
    try:
        novos, total = enqueue_covers(conn)
        log(f"[QA-REMEDIA][capa] enfileirados: {novos} (de {total} publicados sem capa)")
        res = drain_covers(conn, limit=limit)
        log(f"[QA-REMEDIA][capa] processados={res['processados']} "
            f"corrigidos={res['corrigidos']} bloqueados={res.get('bloqueados', 0)} "
            f"quarentena={res['quarentena']}")
        return res
    finally:
        conn.close()


# ============================================================
# Fatia: SINOPSE — reconcile (NÃO-LLM)
# ============================================================
#
# Caso comum revelado em produção: livro PUBLICADO com sinopse VÁLIDA mas
# status_synopsis=0 (flag fora de sincronia com o conteúdo) → is_publishable=0.
# É um defeito de DADO, não de conteúdo — não precisa de LLM. Aqui:
#   sinopse passa validate_synopsis (mesma do pipeline) → status_synopsis=1 →
#   quality_gate (recomputa is_publishable) → publish (upsert) — fix-in-place.
# Sinopse inválida/ausente NÃO é tocada (é caso de regeneração LLM, fatia futura).

FACTOR_SYNOPSIS = "synopsis"


def reconcile_synopsis(conn, limit: int = 50) -> dict:
    """Reconcilia a flag de sinopse dos publicados com status_synopsis=0 cujo
    texto JÁ é válido. Reusa validate_synopsis + quality_gate + publish padrão."""
    from steps.synopsis_import import validate_synopsis
    from steps import quality_gate

    cur = conn.cursor()
    cur.execute("""
        SELECT id, idioma, sinopse FROM livros
        WHERE status_publish = 1 AND status_synopsis = 0
        ORDER BY updated_at DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()

    por_idioma: dict = {}
    validos: list = []
    invalidos = 0
    for lid, idioma, sinopse in rows:
        if validate_synopsis(sinopse or "")[0]:
            por_idioma.setdefault((idioma or "PT"), []).append(lid)
            validos.append(lid)
        else:
            invalidos += 1

    reconciliados = 0
    if validos:
        ph = ",".join("?" * len(validos))
        # Flag correta + limpa quarentena (estamos consertando) + toggle p/ QG/publish.
        # COALESCE: alguns publicados com status_synopsis=0 também têm idioma=NULL
        # (anomalia do review), o que bloquearia o gate. Default PT (catálogo é
        # 99% PT e a sinopse é PT); a checagem de idioma do próprio QG é a rede de
        # segurança — se não for PT, o gate reprova e nada é propagado com erro.
        cur.execute(f"UPDATE livros SET status_synopsis=1, qa_quarantine=0, idioma=COALESCE(idioma,'PT') WHERE id IN ({ph})", tuple(validos))
        cur.execute(f"UPDATE livros SET status_publish=0 WHERE id IN ({ph}) AND status_publish=1", tuple(validos))
        conn.commit()

        # QG por grupo de idioma → a checagem de idioma do gate fica correta.
        for idioma, ids in por_idioma.items():
            quality_gate.run(idioma_base=idioma, book_ids=ids)
        # Propaga ao Supabase (upsert) os que o QG aprovou. publish já é idioma-opcional c/ book_ids.
        publish.run(None, len(validos), book_ids=validos)
        # Robustez: restaura pub=1 p/ quem o publish não levou (ex.: reprovado no QG) — nunca estranda.
        cur.execute(f"UPDATE livros SET status_publish=1 WHERE id IN ({ph}) AND status_publish=0", tuple(validos))
        conn.commit()

        cur.execute(
            f"""SELECT COUNT(*) FROM livros
                WHERE id IN ({ph}) AND status_synopsis=1 AND is_publishable=1 AND status_publish=1""",
            tuple(validos),
        )
        reconciliados = cur.fetchone()[0]

    return {"candidatos": len(rows), "validos": len(validos),
            "reconciliados": reconciliados, "invalidos_llm": invalidos}


def run_synopsis_reconcile(limit: int = 50) -> dict:
    """Passe de reconcile de SINOPSE (não-LLM)."""
    conn = get_conn()
    try:
        res = reconcile_synopsis(conn, limit=limit)
        log(f"[QA-REMEDIA][sinopse-reconcile] candidatos={res['candidatos']} "
            f"válidos={res['validos']} reconciliados={res['reconciliados']} "
            f"inválidos→LLM={res['invalidos_llm']}")
        return res
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="QA — remediação (capas + sinopse reconcile)")
    p.add_argument("--mode", choices=["covers", "synopsis-reconcile"], default="covers")
    p.add_argument("--limit", type=int, default=50)
    a = p.parse_args()
    if a.mode == "covers":
        run_covers(limit=a.limit)
    else:
        run_synopsis_reconcile(limit=a.limit)
