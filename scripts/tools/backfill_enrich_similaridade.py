# ============================================================
# BACKFILL — enrich_similaridade
# Livraria Alexandria
#
# Preenche livros.enrich_similaridade para livros que já foram enriquecidos
# ANTES da coluna existir. Sem a coluna preenchida, a ordenação por confiança
# em synopsis_export não muda nada (tudo NULL empata no fim da fila).
#
# NÃO usa LLM — só a API do Google Books (gratuita). Consultar 11k livros a
# ~0,35 s/consulta leva ~65 min, e não gasta um grama da quota da sessão PRO.
#
# Uso (a partir de scripts/):
#   python tools/backfill_enrich_similaridade.py            # fila de sinopse
#   python tools/backfill_enrich_similaridade.py --limit 200
#   python tools/backfill_enrich_similaridade.py --todos    # todo o catálogo
#
# É retomável: pula quem já tem valor. Pode ser interrompido com Ctrl+C.
# ============================================================

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

from core.db import get_conn, ensure_schema
from core.logger import log
from steps.enrich_descricao import (
    _pick_descricao, GOOGLE_BOOKS_URL, GOOGLE_BOOKS_API_KEY,
    MIN_DESC_LENGTH, REQUEST_DELAY,
)


def _similaridade_remota(titulo, autor):
    """Re-consulta o Google Books e devolve a similaridade que o enrich daria.

    Reconstrói a decisão em vez de recuperá-la: o título do registro original
    não foi persistido. Para ORDENAR a fila isso basta — é um proxy de
    confiança, não uma auditoria do que foi gravado no passado.
    """
    params = {"q": f"{titulo} {autor}".strip(), "maxResults": 5}
    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY

    try:
        res = requests.get(GOOGLE_BOOKS_URL, params=params, timeout=15)
    except requests.RequestException:
        return None

    if res.status_code != 200:
        return None

    candidatos = []
    for item in res.json().get("items", []):
        info = item.get("volumeInfo", {})
        d = info.get("description")
        if d and len(d.strip()) >= MIN_DESC_LENGTH:
            candidatos.append({
                "titulo":    info.get("title", ""),
                "autores":   info.get("authors", []),
                "idioma":    info.get("language", ""),
                "descricao": d.strip(),
            })

    _, _, _, similaridade = _pick_descricao(candidatos, titulo, autor or "")
    return similaridade


def run(limit=None, todos=False):
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()

    # Por padrão só a fila que importa: quem ainda vai consumir uma chamada de
    # sinopse. --todos cobre o catálogo inteiro (muito mais lento, pouco ganho).
    filtro_fila = "" if todos else "AND status_synopsis = 0 AND status_review = 1"
    sql = f"""
        SELECT id, titulo, autor
        FROM livros
        WHERE enrich_similaridade IS NULL
          AND descricao IS NOT NULL AND TRIM(descricao) <> ''
          {filtro_fila}
        ORDER BY priority_score DESC, created_at ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    rows = cur.execute(sql).fetchall()
    total = len(rows)

    if not total:
        log("[BACKFILL_SIM] Nada pendente.")
        conn.close()
        return

    log(f"[BACKFILL_SIM] {total} livro(s) para preencher "
        f"(~{total * REQUEST_DELAY / 60:.0f} min de API)")

    ok = falhas = 0
    try:
        for i, r in enumerate(rows, 1):
            time.sleep(REQUEST_DELAY)
            sim = _similaridade_remota(r["titulo"], r["autor"])

            if sim is None:
                falhas += 1
            else:
                cur.execute(
                    "UPDATE livros SET enrich_similaridade = ? WHERE id = ?",
                    (sim, r["id"]),
                )
                ok += 1

            if i % 50 == 0:
                conn.commit()
                log(f"[BACKFILL_SIM][{i}/{total}] OK={ok} falhas={falhas}")
    except KeyboardInterrupt:
        log("[BACKFILL_SIM] Interrompido — o progresso até aqui foi salvo.")
    finally:
        conn.commit()
        conn.close()

    log(f"[BACKFILL_SIM] Finalizado | OK: {ok} | Falhas: {falhas} | Total: {total}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--todos", action="store_true",
                    help="cobre todo o catálogo, não só a fila de sinopse")
    a = ap.parse_args()
    run(limit=a.limit, todos=a.todos)
