# ============================================================
# STEP 13 — PUBLISH OFERTAS
# Livraria Alexandria
#
# Publica ofertas de livros no Supabase.
# Requisito: livro já publicado (status_publish=1, supabase_id preenchido)
#            e oferta resolvida (offer_status=1, offer_url preenchida).
# ============================================================

import hashlib
import os
import time

from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from core.db import get_conn
from core.logger import log
from steps.offer_resolver import inject_ml_affiliate, inject_amazon_tag


# =========================
# CONFIG
# =========================

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

TIMEOUT     = 60
MAX_RETRIES = 3


# =========================
# FETCH
# =========================

def fetch_pendentes(conn, pacote):

    cur = conn.cursor()

    # `preco_atual` PRIMEIRO, `preco` só como fallback — mesma regra que o
    # pipeline de jogos já usa (SUPABASE_PAYLOAD_COLUMNS).
    #
    # `preco` é a coluna SEMENTE (só o offer_seed e o db_recover escrevem nela);
    # quem coleta preço de verdade — marketplace_scraper.save_result e
    # offer_price_monitor — grava em `preco_atual`. Publicar `preco` significava
    # publicar quase sempre NULL. Medido em 2026-07-26 no books.db: 2 livros com
    # `preco`, 58 com `preco_atual`; dos 4.403 elegíveis à publicação, 0 tinham
    # `preco` e 57 tinham `preco_atual`. No Supabase o efeito era 4.577 das 4.579
    # ofertas ativas sem preço, e a página /ofertas exibindo "Consulte o site"
    # em ~100% das linhas.
    cur.execute("""
        SELECT
            id,
            titulo,
            supabase_id,
            marketplace,
            offer_url,
            COALESCE(preco_atual, preco) AS preco,
            oferta_payload_hash
        FROM livros
        WHERE CAST(offer_status AS TEXT) IN ('1', 'active')
          AND status_publish        = 1
          AND status_publish_oferta = 0
          AND offer_url             IS NOT NULL
          AND supabase_id           IS NOT NULL
        LIMIT ?
    """, (pacote,))

    return cur.fetchall()


# =========================
# UPSERT
# =========================

def upsert(url, payload, headers):

    for attempt in range(MAX_RETRIES):

        try:
            res = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=TIMEOUT
            )

            if res.status_code == 409:
                return True

            if res.status_code not in [200, 201]:
                log(f"SUPABASE ERRO {res.status_code} → {res.text[:200]}")
                time.sleep(2)
                continue

            return True

        except Exception as e:
            log(f"RETRY → {e}")
            time.sleep(2)

    return False


# =========================
# MIGRAÇÃO: normaliza offer_status='active' → 1 e reseta flag
# =========================

def fix_offer_status(conn=None):
    """Converte offer_status='active' para 1 (inteiro) e reseta status_publish_oferta=0.

    Livros seeds importados com offer_status='active' (texto) nunca eram
    elegíveis para step 17 (exige offer_status=1 inteiro). Esta função
    corrige o estado para que possam ser publicados.

    Retorna `(com_url, sem_url)`. O log separa, dentro de `sem_url`, quem é fila
    real do step 3 de quem está bloqueado a montante por falta de `lookup_query`
    — ver o comentário no fim da função.

    Também recupera ofertas em offer_status='error': o offer_price_monitor
    marca 'error' quando falha ao BUSCAR a página da oferta (bloqueio/timeout
    transitório da Amazon) — mas deixa offer_url e status_publish intactos.
    Esse estado é morto: inelegível para publicar (exige status active), invisível
    para re-resolver (exige offer_url NULL) e mesmo assim contado pela auditoria.
    Como offer_url continua válida (tipicamente link de busca, forma usada por
    ~metade das ofertas ativas), normalizar 'error' → 1 as devolve ao fluxo de
    publicação. NÃO toca em 'unavailable' (indisponibilidade real, com
    is_publishable=0).
    """
    from core.db import get_conn as _get_conn
    close_conn = conn is None
    if conn is None:
        conn = _get_conn()

    cur = conn.cursor()

    # 1. Normaliza offer_status texto → inteiro e reseta o flag de publicação
    #    ('active' = seeds legados; 'error' = falha transitória do price monitor)
    cur.execute("""
        UPDATE livros
        SET offer_status         = 1,
            status_publish_oferta = 0,
            updated_at           = CURRENT_TIMESTAMP
        WHERE offer_status IN ('active', 'error')
          AND offer_url IS NOT NULL
    """)
    conn.commit()
    com_url = cur.rowcount

    # 2. Reseta flag para livros 'active' sem offer_url (serão resolvidos no step 3)
    cur.execute("""
        UPDATE livros
        SET status_publish_oferta = 0,
            updated_at            = CURRENT_TIMESTAMP
        WHERE offer_status = 'active'
          AND offer_url IS NULL
    """)
    conn.commit()
    sem_url = cur.rowcount

    # Quantos desses o step 3 pode de fato alcançar. `offer_resolver.fetch_pending`
    # exige `lookup_query IS NOT NULL`, então quem está sem lookup_query não é fila
    # do step 3 — está bloqueado a montante.
    cur.execute("""
        SELECT COUNT(*) FROM livros
        WHERE offer_status = 'active'
          AND offer_url IS NULL
          AND (lookup_query IS NULL OR TRIM(lookup_query) = '')
    """)
    sem_lookup = cur.fetchone()[0]
    fila_step3 = sem_url - sem_lookup

    if close_conn:
        conn.close()

    log(f"[OFERTAS] fix_offer_status: {com_url} offer_status normalizados → 1 (offer_url preenchida)")
    if fila_step3:
        log(f"[OFERTAS] fix_offer_status: {fila_step3} livros sem offer_url na fila do step 3 "
            f"(o autopilot resolve no próximo passe)")
    if sem_lookup:
        # ⚠ Esta linha dizia "rodar step 3 primeiro" até 2026-08-26, e era falso.
        # Medido nos logs pipeline_2026-08-23_10-20-27 (14 ocorrências) e
        # pipeline_2026-08-24_20-09-02 (43): o número ficou IMÓVEL em 179 em todas
        # elas, com o autopilot rodando o step 3 várias vezes no intervalo,
        # inclusive um lote de fallback de 1.000. A causa é que os 179 estão com
        # `lookup_query` NULL, e o step 3 filtra por ela — "rodar o step 3
        # primeiro" é impossível por construção, não uma pendência do usuário.
        #
        # E a exclusão deles é CORRETA: são títulos EN (periódicos e catálogos de
        # biblioteca), e `tools/backfill_lookup_query.py` usa por padrão o escopo
        # `pt_confirmado`, que os deixa de fora de propósito — resolver oferta para
        # não-PT gasta requisição no marketplace para livro que o quality_gate vai
        # reprovar por idioma. O defeito era só a mensagem.
        log(f"[OFERTAS] fix_offer_status: {sem_lookup} livros sem offer_url E sem "
            f"lookup_query — fora do alcance do step 3 (backfill de lookup_query "
            f"exclui não-PT de propósito); nada a fazer")
    return com_url, sem_url


# =========================
# FLAG LOCAL
# =========================

def _offer_url_final(offer_url):
    """URL como ela vai ao Supabase — com as tags de afiliado já injetadas.

    Existe para o `run_repair` e o `run` hasharem exatamente a MESMA string. Se
    o repair hasheasse a URL crua do banco e o publish a URL com tag, todo hash
    divergiria e o filtro de mudança não filtraria nada.
    """
    return inject_amazon_tag(inject_ml_affiliate(offer_url))


def _payload_hash(marketplace, offer_url, preco) -> str:
    """Impressão digital do que de fato vai ao Supabase.

    Cobre os três campos mutáveis do payload — `marketplace`, `url_afiliada` e
    `preco`. Fora de propósito: `livro_id` (imutável), `ativa` (sempre True
    nesta query, que já filtra offer_status ativo) e `created_at` (muda a cada
    chamada por construção, e incluí-lo faria todo hash diferir sempre).

    O preço é arredondado a 2 casas antes de entrar: é NUMERIC no Supabase e
    REAL no SQLite, e um ruído de ponto flutuante na 12ª casa não é mudança de
    preço — seria republicação eterna.
    """
    preco_norm = "" if preco is None else f"{round(float(preco), 2):.2f}"
    base = f"{marketplace or ''}|{offer_url or ''}|{preco_norm}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def mark_published(conn, local_id, payload_hash=None):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET status_publish_oferta = 1,
            oferta_payload_hash   = COALESCE(?, oferta_payload_hash),
            updated_at            = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (payload_hash, local_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(pacote=100):

    conn = get_conn()

    supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not supabase_key:
        log("ERRO: NEXT_PUBLIC_SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não configurados.")
        conn.close()
        return

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        # upsert por (livro_id, marketplace): cria se não existe, atualiza se já existe
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    # on_conflict=(livro_id,marketplace) — requer UNIQUE(livro_id, marketplace) no Supabase
    ofertas_url = f"{supabase_url}/rest/v1/ofertas?on_conflict=livro_id,marketplace"

    rows = fetch_pendentes(conn, pacote)

    if not rows:
        log("Nenhuma oferta pendente para publicação.")
        conn.close()
        return

    inserted = 0
    failed   = 0
    total    = len(rows)

    now = datetime.utcnow().isoformat()

    for i, row in enumerate(rows, start=1):

        local_id, titulo, supabase_id, marketplace, offer_url, preco, hash_atual = row

        offer_url = _offer_url_final(offer_url)

        payload = {
            "livro_id":    supabase_id,
            "marketplace": marketplace,
            "url_afiliada": offer_url,
            "preco":       preco,
            "ativa":       True,
        }

        # `created_at` SÓ na primeira publicação desta oferta. Com
        # `resolution=merge-duplicates` o PostgREST sobrescreve as colunas
        # enviadas, então mandá-la em toda republicação reescrevia a data de
        # criação de cada oferta a cada passe do run_repair — medido no
        # pipeline_2026-08-12_19-03-07: 9.630 republicações em 35h, ou seja o
        # `created_at` de TODAS as ofertas reescrito 2x. É o mesmo defeito já
        # corrigido em publish_autores._resync_bios.
        if hash_atual is None:
            payload["created_at"] = now

        ok = upsert(ofertas_url, payload, headers)

        if not ok:
            failed += 1
            log(f"[OFERTAS][{i:03d}/{total:03d}] FALHA → {titulo}")
            continue

        mark_published(conn, local_id, _payload_hash(marketplace, offer_url, preco))
        inserted += 1
        log(f"[OFERTAS][{i:03d}/{total:03d}] OK → {titulo} ({marketplace})")

    conn.close()

    log(f"Ofertas publicadas: {inserted} | Falhas: {failed}")


# =========================
# REPAIR
# =========================

def run_repair(pacote=200):
    """Republica as ofertas cujo payload MUDOU desde a última publicação.

    1. Normaliza offer_status='active' → 1
    2. Marca para republicação só quem tem payload diferente do já publicado
    3. Chama run(pacote) — upsert idempotente via on_conflict

    ⚠ Até 2026-08-14 o passo 2 resetava `status_publish_oferta=0` para TODOS os
    publicados, e o passo 3 reenviava o catálogo inteiro. Medido no
    pipeline_2026-08-12_19-03-07 (35h27): 4.789 ofertas distintas e **9.630
    publicações** — 2 execuções do repair × o catálogo inteiro, 99 passes de
    100, e 52,6% de todas as linhas do log.

    O que de fato muda entre passes é preço, e o `offer_price_monitor` visita
    `PRECO_POR_CICLO` livros por ciclo (padrão 50). Reenviar ~4.800 upserts para
    propagar ~50 preços é ~99% de escrita inútil no Supabase.

    O filtro é por hash do payload (`_payload_hash`), não por timestamp: o
    `updated_at` é tocado por vários steps — inclusive pelo próprio repair, na
    versão anterior — então não serve de sinal de mudança. O hash cobre
    marketplace, URL afiliada e preço; qualquer um deles mudando republica.
    """
    conn = get_conn()

    # 1. Normaliza offer_status
    fix_offer_status(conn)

    # 2. Marca só o que mudou
    cur = conn.cursor()
    cur.execute("""
        SELECT id, marketplace, offer_url,
               COALESCE(preco_atual, preco) AS preco,
               oferta_payload_hash, status_publish_oferta
        FROM livros
        WHERE status_publish   = 1
          AND offer_url        IS NOT NULL
          AND CAST(offer_status AS TEXT) IN ('1', 'active')
          AND supabase_id      IS NOT NULL
    """)
    elegiveis = cur.fetchall()

    mudaram = []
    for local_id, marketplace, offer_url, preco, hash_ant, ja_pendente in elegiveis:
        novo = _payload_hash(marketplace, _offer_url_final(offer_url), preco)
        # hash_ant NULL = nunca publicada por esta versão do código: publica uma
        # vez para semear o hash. A partir daí só volta se mudar de verdade.
        if hash_ant != novo:
            mudaram.append(local_id)

    if mudaram:
        cur.executemany(
            "UPDATE livros SET status_publish_oferta = 0 WHERE id = ?",
            [(i,) for i in mudaram],
        )
        conn.commit()
    conn.close()

    inalterados = len(elegiveis) - len(mudaram)
    log(f"[REPAIR] {len(mudaram)} oferta(s) com payload alterado → republicar | "
        f"{inalterados} inalterada(s) — puladas")

    if not mudaram:
        return

    # 3. Re-publica (pode levar mais de um passe se `mudaram` > pacote)
    run(pacote)
