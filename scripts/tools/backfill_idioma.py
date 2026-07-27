# ============================================================
# BACKFILL — idioma (via Google Books)
# Livraria Alexandria
#
# Preenche livros.idioma a partir do campo `volumeInfo.language` do Google
# Books, que e METADADO do volume — nao heuristica.
#
# Por que nao heuristica (medido em 2026-07-26, n=17.861):
#   - Detectar pelo texto da `descricao` NAO funciona: o enrich usa descricao
#     em EN quando nao ha PT, entao 45% dos livros JA PUBLICADOS (2.037 de
#     4.512) sao classificados como ingles — incluindo "Diario de um Banana",
#     "Estrategia Competitiva" e "1984". Aplicar isso despublicaria ~2 mil
#     livros reais.
#   - Detectar pelo TITULO com stopwords fica 65% inconclusivo (242 dos 368) e
#     subdetecta: perde "Routledge Handbook of Macroeconomic Methodology" e
#     "Macroeconomics in the Global Economy", porque titulo tecnico curto nao
#     tem stopword suficiente.
#
# Contexto do problema: os 17.727 livros do banco estao TODOS com idioma='PT'
# (nenhum EN/ES/IT), entao o check_language do quality_gate — que compara o
# CAMPO idioma com idioma_base='PT' — nunca reprovou nada em todo o catalogo.
#
# NAO usa LLM: so a API do Google Books. Nao gasta quota da sessao PRO.
# Cota gratuita ~1.000 consultas/dia (429 "Queries per day" ao estourar).
#
# Uso (a partir de scripts/):
#   python tools/backfill_idioma.py                 # livros sem offer_url travados
#   python tools/backfill_idioma.py --limit 50
#   python tools/backfill_idioma.py --escopo publicados --dry-run
#
# Retomavel: pula quem ja tem idioma_checado_em. Ctrl+C a qualquer momento.
# ============================================================

import argparse
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

from core.db import get_conn
from core.logger import log
from steps.enrich_descricao import (
    GOOGLE_BOOKS_URL,
    GOOGLE_BOOKS_API_KEY,
    REQUEST_DELAY,
    _similaridade_titulo,
)

# Limiar de casamento de titulo para ACEITAR o idioma do volume retornado.
#
# Deliberadamente mais alto que o TITLE_SIMILARITY_THRESHOLD=0.5 usado pelo
# enrich: la, um casamento fraco custa uma descricao ruim que o agente rejeita
# depois; aqui custa marcar um livro PT como EN, o que o tira da publicacao em
# definitivo (o quality_gate reprova idioma != PT). Erro caro, entao so
# aceitamos casamento forte — o resto fica intacto para decisao humana.
SIM_MINIMA = 0.75

# Google Books devolve BCP-47 ("pt", "pt-BR", "en", "en-GB"). O pipeline usa
# PT|EN|ES|IT|UNKNOWN (ver "Tabela livros" no scripts/CLAUDE.md).
MAPA_IDIOMA = {"pt": "PT", "en": "EN", "es": "ES", "it": "IT"}

ESCOPOS = {
    # Os travados: status_enrich=0 sem offer_url. Sao 368 (2026-07-26), todos
    # sem lookup_query, e o alvo original deste backfill.
    "travados": "status_enrich = 0",
    "publicados": "status_publish = 1",
    "todos": "1 = 1",
}


def mapear_idioma(code):
    """'pt-BR' -> 'PT'. Retorna None para codigo ausente ou fora do mapa."""
    if not code:
        return None
    return MAPA_IDIOMA.get(str(code).strip().lower().split("-")[0])


def garantir_coluna(conn):
    """Cria idioma_checado_em se faltar — e o que torna o backfill retomavel."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(livros)")]
    if "idioma_checado_em" not in cols:
        conn.execute("ALTER TABLE livros ADD COLUMN idioma_checado_em TEXT")
        conn.commit()
        log("[IDIOMA] coluna idioma_checado_em criada")


def consultar(titulo, autor, isbn):
    """Retorna (codigo_idioma, titulo_retornado) ou (None, None).

    ISBN primeiro: identifica a EDICAO, entao o idioma vem sem ambiguidade e
    dispensa o casamento de titulo. Sem ISBN, cai na busca por titulo+autor e
    o chamador confere a similaridade antes de aceitar.
    """
    tentativas = []
    if isbn:
        tentativas.append(("isbn:%s" % isbn, True))
    q = (titulo or "").strip()
    if q:
        if autor:
            tentativas.append(('intitle:"%s" inauthor:"%s"' % (q, autor.strip()), False))
        tentativas.append(('intitle:"%s"' % q, False))

    for termo, por_isbn in tentativas:
        params = {"q": termo, "maxResults": 1}
        if GOOGLE_BOOKS_API_KEY:
            params["key"] = GOOGLE_BOOKS_API_KEY
        try:
            r = requests.get(GOOGLE_BOOKS_URL, params=params, timeout=20)
        except Exception as e:
            log("[IDIOMA] erro HTTP: %s" % type(e).__name__)
            time.sleep(REQUEST_DELAY)
            continue

        if r.status_code == 429:
            raise RuntimeError("Google Books 429 — cota diaria esgotada")
        if r.status_code != 200:
            time.sleep(REQUEST_DELAY)
            continue

        itens = (r.json() or {}).get("items") or []
        time.sleep(REQUEST_DELAY)
        if not itens:
            continue
        vi = itens[0].get("volumeInfo", {})
        code = vi.get("language")
        if not code:
            continue
        # Casamento por ISBN dispensa conferir titulo (edicao exata).
        return code, (None if por_isbn else vi.get("title") or "")
    return None, None


def run(escopo="travados", limite=None, dry_run=False):
    conn = get_conn()
    garantir_coluna(conn)
    cur = conn.cursor()

    sql = (
        "SELECT id, titulo, autor, isbn, idioma FROM livros "
        "WHERE (%s) AND idioma_checado_em IS NULL "
        "ORDER BY created_at" % ESCOPOS[escopo]
    )
    if limite:
        sql += " LIMIT %d" % int(limite)
    rows = cur.execute(sql).fetchall()

    log("[IDIOMA] escopo=%s | pendentes=%d | dry_run=%s" % (escopo, len(rows), dry_run))
    if not rows:
        conn.close()
        return

    n_ok = n_mudou = n_sem = n_fraco = 0
    agora = datetime.utcnow().isoformat()

    try:
        for i, row in enumerate(rows, 1):
            livro_id, titulo, autor, isbn, idioma_atual = (
                row["id"], row["titulo"], row["autor"], row["isbn"], row["idioma"],
            )
            try:
                code, titulo_ret = consultar(titulo, autor, isbn)
            except RuntimeError as e:
                log("[IDIOMA] %s — parando; rode de novo quando a cota resetar." % e)
                break

            novo = mapear_idioma(code)

            if novo and titulo_ret is not None:
                sim = _similaridade_titulo(titulo or "", titulo_ret)
                if sim < SIM_MINIMA:
                    n_fraco += 1
                    log("[IDIOMA][%d/%d] casamento fraco (%.2f) — mantido: %s"
                        % (i, len(rows), sim, str(titulo)[:44]))
                    novo = None

            if not novo:
                n_sem += 1
                if not dry_run:
                    # Marca como checado mesmo sem resposta: sem isto o tool
                    # re-consulta os mesmos livros a cada execucao e queima a
                    # cota diaria sem avancar.
                    cur.execute(
                        "UPDATE livros SET idioma_checado_em=? WHERE id=?",
                        (agora, livro_id),
                    )
                    conn.commit()
                continue

            n_ok += 1
            mudou = novo != (idioma_atual or "")
            if mudou:
                n_mudou += 1
                log("[IDIOMA][%d/%d] %s -> %s | %s"
                    % (i, len(rows), idioma_atual, novo, str(titulo)[:44]))
            if not dry_run:
                cur.execute(
                    "UPDATE livros SET idioma=?, idioma_checado_em=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (novo, agora, livro_id),
                )
                conn.commit()
    except KeyboardInterrupt:
        log("[IDIOMA] interrompido — progresso salvo.")

    conn.close()
    log("[IDIOMA] resolvidos: %d | idioma alterado: %d | sem resposta: %d | "
        "casamento fraco: %d" % (n_ok, n_mudou, n_sem, n_fraco))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill de livros.idioma via Google Books")
    ap.add_argument("--escopo", choices=sorted(ESCOPOS), default="travados")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(escopo=a.escopo, limite=a.limit, dry_run=a.dry_run)
