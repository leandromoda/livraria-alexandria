# ============================================================
# BACKFILL — lookup_query
# Livraria Alexandria
#
# Preenche livros.lookup_query, que e o INSUMO do step 3 (offer_resolver):
# `fetch_pending` filtra por `lookup_query IS NOT NULL`, entao livro sem esse
# campo nunca resolve oferta, nunca ganha offer_url e por isso tambem nunca
# entra na fila do step 4 (marketplace_scraper, que exige offer_url).
#
# Origem do problema (medido em 2026-07-27): 368 livros com status_enrich=0
# estavam TODOS sem lookup_query. Todos com seed_id NULL e criados entre
# 2026-02-13 e 2026-02-16 — nao vieram do offer_seed, que rejeita seed sem
# lookup_query, e sim de alguma carga em massa do inicio do projeto.
#
# NAO usa rede nem LLM: monta a query a partir de titulo + autor.
#
# Uso (a partir de scripts/):
#   python tools/backfill_lookup_query.py --dry-run
#   python tools/backfill_lookup_query.py
#   python tools/backfill_lookup_query.py --escopo qualquer_pt
#
# Idempotente: so toca em quem esta sem lookup_query.
# ============================================================

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.db import get_conn
from core.logger import log

# Sufixo do padrao ja usado no catalogo ("Caminhos da Mente Daniel Kahneman
# livro"): ancora a busca do marketplace em livro e reduz match com filme,
# curso ou brinquedo de mesmo nome.
SUFIXO = "livro"

ESCOPOS = {
    # Padrao: so quem o Google Books CONFIRMOU como portugues.
    #
    # Nao basta idioma='PT': depois do backfill de idioma, 62 dos 221 PT
    # ficaram com idioma_fonte 'fraco' ou 'sem_resposta', isto e, o idioma
    # nunca foi verificado — entre eles "The Great Gatsby" e "Northanger
    # Abbey". Resolver oferta para esses gastaria requisicao no marketplace
    # para livro que o quality_gate vai reprovar por idioma assim que a
    # verificacao acontecer.
    "pt_confirmado": "idioma = 'PT' AND idioma_fonte = 'google'",
    "qualquer_pt": "idioma = 'PT'",
    "todos": "1 = 1",
}


def _limpa(s):
    """Tira o que atrapalha a busca do marketplace, preservando acento.

    Subtitulo depois de ':' sai porque o titulo do anuncio raramente o traz
    ("Racionais MC's: Sobrevivendo no Inferno" -> "Racionais MCs").
    """
    s = (s or "").strip()
    s = s.split(":")[0]
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[\[\](){}\"/\\|<>*#@_]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .,;-")


def montar(titulo, autor):
    """Retorna a lookup_query ou None se nem o titulo servir."""
    t = _limpa(titulo)
    if not t:
        return None
    # Autor institucional longo ("Inter-American Development Bank, Research
    # Dept.") polui a busca mais do que ajuda; corta no primeiro nome composto.
    a = _limpa((autor or "").split(",")[0])
    partes = [t]
    if a and len(a) <= 40:
        partes.append(a)
    partes.append(SUFIXO)
    return " ".join(partes)


def run(escopo="pt_confirmado", limite=None, dry_run=False):
    conn = get_conn()
    cur = conn.cursor()

    sql = (
        "SELECT id, titulo, autor FROM livros "
        "WHERE (lookup_query IS NULL OR TRIM(lookup_query) = '') "
        "AND (%s) ORDER BY created_at" % ESCOPOS[escopo]
    )
    if limite:
        sql += " LIMIT %d" % int(limite)
    rows = cur.execute(sql).fetchall()

    log("[LOOKUP] escopo=%s | sem lookup_query=%d | dry_run=%s"
        % (escopo, len(rows), dry_run))

    n_ok = n_pulado = 0
    for row in rows:
        q = montar(row["titulo"], row["autor"])
        if not q:
            n_pulado += 1
            continue
        n_ok += 1
        if n_ok <= 5:
            log("[LOOKUP] %s  ->  %s" % (str(row["titulo"])[:36], q[:60]))
        if not dry_run:
            cur.execute(
                "UPDATE livros SET lookup_query=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?", (q, row["id"]))
    if not dry_run:
        conn.commit()
    conn.close()
    log("[LOOKUP] preenchidos: %d | pulados (sem titulo util): %d" % (n_ok, n_pulado))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill de livros.lookup_query")
    ap.add_argument("--escopo", choices=sorted(ESCOPOS), default="pt_confirmado")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(escopo=a.escopo, limite=a.limit, dry_run=a.dry_run)
