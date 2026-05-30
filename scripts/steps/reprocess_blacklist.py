# ============================================================
# WS5 — REPROCESSAR TÍTULOS DESPUBLICADOS PELA BLACKLIST
# Livraria Alexandria
#
# Hoje apply_blacklist (opção 45) despublica severity medium|high e
# persiste a CAUSA (blacklist_reason/severity). Este módulo recupera os
# títulos com causa RECUPERÁVEL: reseta o status apropriado para que a
# geração os refaça, contando tentativas. Causas não recuperáveis
# (não-livro, duplicado, título incompatível) ou que excedem o max-retry
# vão para QUARENTENA definitiva (qa_quarantine=1 — não reentram na fila).
#
# Sem LLM — apenas reclassifica estado no SQLite. A regeneração em si é
# feita pelo motor batch (opção O / menu 11/10) e revalidada pelo QA/QG.
# ============================================================

import os

from core.db import get_conn
from core.logger import log

MAX_QA_RETRY = int(os.getenv("MAX_QA_RETRY", "2"))


# =========================
# CLASSIFICAÇÃO DA CAUSA
# =========================

# Causas "hard" — nunca reentram (problema de dados, não de geração).
_HARD_MARKERS = (
    "non-book", "not-a-book", "not_book", "nonbook", "nao-livro", "não-livro",
    "duplicate", "duplicad", "title-mismatch", "title_mismatch", "mismatch",
    "hard",
)


def classify_cause(reason: str) -> str:
    """Retorna a ação para uma causa de blacklist:
      'synopsis'   → resetar status_synopsis=0 (regenerar sinopse)
      'categorize' → resetar status_categorize=0 (recategorizar)
      'offer'      → marcar reactivation_pending=1 (revisão manual de oferta)
      'quarantine' → quarentena definitiva (hard ou desconhecida)
    """
    r = (reason or "").strip().lower()
    if not r:
        return "quarantine"
    if any(m in r for m in _HARD_MARKERS):
        return "quarantine"
    if "categor" in r:
        return "categorize"
    if "offer" in r or "oferta" in r:
        return "offer"
    if r.startswith("synopsis") or "synopsis" in r or "sinopse" in r:
        return "synopsis"
    # Causa desconhecida → conservador: não entrar em loop.
    return "quarantine"


# =========================
# SELEÇÃO
# =========================

def _fetch_candidates(conn, limit=None):
    """Blacklistados ainda não reprocessados: com causa registrada, fora da
    quarentena e ainda com o sentinela status_*=4."""
    cur = conn.cursor()
    sql = """
        SELECT id, titulo, slug, blacklist_reason, blacklist_severity,
               COALESCE(qa_retry, 0) AS qa_retry
        FROM livros
        WHERE blacklist_reason IS NOT NULL
          AND COALESCE(qa_quarantine, 0) = 0
          AND (status_synopsis = 4 OR status_categorize = 4)
        ORDER BY blacklist_severity DESC, updated_at ASC
    """
    if limit:
        sql += " LIMIT ?"
        cur.execute(sql, (limit,))
    else:
        cur.execute(sql)
    return cur.fetchall()


# =========================
# AÇÕES
# =========================

def _quarantine(conn, livro_id, motivo):
    conn.execute(
        """UPDATE livros
           SET qa_quarantine = 1,
               updated_at    = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (livro_id,),
    )
    conn.commit()


def _reset_for_regen(conn, livro_id, status_col):
    """Reseta o status recuperável para 0 e incrementa qa_retry. O livro
    reentra na fila de geração; is_publishable permanece 0 até o QG reavaliar."""
    conn.execute(
        f"""UPDATE livros
            SET {status_col}  = 0,
                qa_retry      = COALESCE(qa_retry, 0) + 1,
                updated_at    = CURRENT_TIMESTAMP
            WHERE id = ?""",
        (livro_id,),
    )
    conn.commit()


def _flag_offer_manual(conn, livro_id):
    conn.execute(
        """UPDATE livros
           SET reactivation_pending = 1,
               qa_retry             = COALESCE(qa_retry, 0) + 1,
               updated_at           = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (livro_id,),
    )
    conn.commit()


# =========================
# RUN
# =========================

def run(dry_run: bool = False, limit=None) -> dict:
    log(f"[REPROCESS_BL] Iniciando (max_retry={MAX_QA_RETRY}, dry_run={dry_run})")

    conn = get_conn()
    rows = _fetch_candidates(conn, limit=limit)

    counts = {
        "total": len(rows),
        "regen_synopsis": 0,
        "regen_categorize": 0,
        "offer_manual": 0,
        "quarantined": 0,
    }

    if not rows:
        log("[REPROCESS_BL] Nenhum título recuperável pendente.")
        conn.close()
        return counts

    for row in rows:
        livro_id = row["id"]
        titulo   = row["titulo"]
        reason   = row["blacklist_reason"]
        retry    = row["qa_retry"]
        action   = classify_cause(reason)

        # Esgotou tentativas → quarentena, independentemente da causa.
        if action in ("synopsis", "categorize", "offer") and retry >= MAX_QA_RETRY:
            log(f"[REPROCESS_BL] QUARENTENA (max-retry {retry}≥{MAX_QA_RETRY}) → {titulo} | {reason}")
            if not dry_run:
                _quarantine(conn, livro_id, reason)
            counts["quarantined"] += 1
            continue

        if action == "quarantine":
            log(f"[REPROCESS_BL] QUARENTENA (causa hard/desconhecida) → {titulo} | {reason}")
            if not dry_run:
                _quarantine(conn, livro_id, reason)
            counts["quarantined"] += 1

        elif action == "synopsis":
            log(f"[REPROCESS_BL] regen sinopse (retry→{retry+1}) → {titulo} | {reason}")
            if not dry_run:
                _reset_for_regen(conn, livro_id, "status_synopsis")
            counts["regen_synopsis"] += 1

        elif action == "categorize":
            log(f"[REPROCESS_BL] recategorizar (retry→{retry+1}) → {titulo} | {reason}")
            if not dry_run:
                _reset_for_regen(conn, livro_id, "status_categorize")
            counts["regen_categorize"] += 1

        elif action == "offer":
            log(f"[REPROCESS_BL] oferta → revisão manual (reactivation_pending) → {titulo} | {reason}")
            if not dry_run:
                _flag_offer_manual(conn, livro_id)
            counts["offer_manual"] += 1

    conn.close()

    log("[REPROCESS_BL] Finalizado"
        + (" (dry-run — nada aplicado)" if dry_run else ""))
    log(f"[REPROCESS_BL] Total: {counts['total']} | "
        f"regen sinopse: {counts['regen_synopsis']} | "
        f"recategorizar: {counts['regen_categorize']} | "
        f"oferta manual: {counts['offer_manual']} | "
        f"quarentena: {counts['quarantined']}")
    return counts


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Reprocessa títulos despublicados pela blacklist (WS5)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args()
    run(dry_run=a.dry_run, limit=a.limit)
