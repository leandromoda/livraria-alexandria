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

# Procedencia gravada em livros.idioma_fonte. Sem ela, "PT confirmado pelo
# Google" e "nao consegui resolver, ficou PT" sao indistinguiveis no banco —
# foi o que travou o passo seguinte na 1a execucao (2026-07-27): preencher
# lookup_query nos 235 "PT" resolveria oferta para livro alemao e ingles.
FONTE_GOOGLE = "google"          # respondeu e o idioma esta no dominio
FONTE_NAO_MAPEADO = "nao_mapeado"  # respondeu de/fr/... -> idioma vira UNKNOWN
FONTE_FRACO = "fraco"            # titulo casou abaixo de SIM_MINIMA
FONTE_SEM_RESPOSTA = "sem_resposta"

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
    """idioma_checado_em torna o backfill retomavel; idioma_fonte registra a
    procedencia, sem a qual nao da para saber em quem confiar depois."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(livros)")]
    for nome in ("idioma_checado_em", "idioma_fonte"):
        if nome not in cols:
            conn.execute("ALTER TABLE livros ADD COLUMN %s TEXT" % nome)
            conn.commit()
            log("[IDIOMA] coluna %s criada" % nome)


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

    tot = {FONTE_GOOGLE: 0, FONTE_NAO_MAPEADO: 0, FONTE_FRACO: 0,
           FONTE_SEM_RESPOSTA: 0, "alterado": 0}
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
            fonte = FONTE_SEM_RESPOSTA

            # Casamento fraco: o volume pode ser outro livro, entao o idioma
            # dele nao vale. Mantem o que estava.
            if code and titulo_ret is not None:
                sim = _similaridade_titulo(titulo or "", titulo_ret)
                if sim < SIM_MINIMA:
                    tot[FONTE_FRACO] += 1
                    if not dry_run:
                        cur.execute(
                            "UPDATE livros SET idioma_checado_em=?, idioma_fonte=? "
                            "WHERE id=?", (agora, FONTE_FRACO, livro_id))
                        conn.commit()
                    continue

            if code and not novo:
                # Google respondeu 'de'/'fr'/... — dominio do pipeline nao
                # representa, mas e informacao FORTE de que nao e PT. UNKNOWN
                # reprova no check_language do quality_gate, que e o desejado.
                novo = "UNKNOWN"
                fonte = "%s:%s" % (FONTE_NAO_MAPEADO, str(code).lower()[:8])
                tot[FONTE_NAO_MAPEADO] += 1
            elif novo:
                fonte = FONTE_GOOGLE
                tot[FONTE_GOOGLE] += 1
            else:
                tot[FONTE_SEM_RESPOSTA] += 1
                if not dry_run:
                    # Marca como checado mesmo sem resposta: sem isto o tool
                    # re-consulta os mesmos livros a cada execucao e queima a
                    # cota diaria sem avancar.
                    cur.execute(
                        "UPDATE livros SET idioma_checado_em=?, idioma_fonte=? "
                        "WHERE id=?", (agora, FONTE_SEM_RESPOSTA, livro_id))
                    conn.commit()
                continue

            if novo != (idioma_atual or ""):
                tot["alterado"] += 1
                log("[IDIOMA][%d/%d] %s -> %s (%s) | %s"
                    % (i, len(rows), idioma_atual, novo, fonte, str(titulo)[:40]))
            if not dry_run:
                cur.execute(
                    "UPDATE livros SET idioma=?, idioma_checado_em=?, idioma_fonte=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (novo, agora, fonte, livro_id))
                conn.commit()
    except KeyboardInterrupt:
        log("[IDIOMA] interrompido — progresso salvo.")

    conn.close()
    log("[IDIOMA] google: %d | nao mapeado (->UNKNOWN): %d | casamento fraco: %d "
        "| sem resposta: %d | idioma alterado: %d"
        % (tot[FONTE_GOOGLE], tot[FONTE_NAO_MAPEADO], tot[FONTE_FRACO],
           tot[FONTE_SEM_RESPOSTA], tot["alterado"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill de livros.idioma via Google Books")
    ap.add_argument("--escopo", choices=sorted(ESCOPOS), default="travados")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(escopo=a.escopo, limite=a.limit, dry_run=a.dry_run)
