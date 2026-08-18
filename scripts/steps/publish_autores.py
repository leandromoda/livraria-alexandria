# ============================================================
# STEP — PUBLISH AUTORES
# Livraria Alexandria
#
# Publica autores e relações livros_autores no Supabase.
# ============================================================

import os

import requests
import time

from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from core.db import get_conn
from core.logger import log
from core import interrupt as _interrupt


# =========================
# CONFIG
# =========================

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=representation"
}

TIMEOUT     = 60
MAX_RETRIES = 3


# =========================
# FETCH
# =========================

def fetch_autores_pendentes(conn, pacote):

    cur = conn.cursor()

    # EXISTS obrigatório: autor sem nenhum livro vinculado não vai ao Supabase.
    # Sem esse filtro qualquer autor com status_publish=0 era publicado, inclusive
    # os que ficaram sem obra (livro removido por dedup/blacklist depois, ou autor
    # criado antes do vínculo). Medido em 2026-08-18: 642 dos 8.342 autores
    # publicados não tinham NENHUMA linha em livros_autores — e nenhum deles tinha
    # sequer um livro cujo campo `autor` casasse com o nome, ou seja, não era
    # junção perdida, era autor sem obra. Como app/sitemap.ts lista todos os
    # autores sem filtro, cada um virava uma página vazia submetida ao Google.
    #
    # Isto estanca a ORIGEM. O passivo já publicado é filtrado no sitemap.
    cur.execute("""
        SELECT id, nome, slug, nacionalidade, supabase_id, descricao
        FROM autores a
        WHERE status_publish = 0
          AND EXISTS (SELECT 1 FROM livros_autores la WHERE la.autor_id = a.id)
        LIMIT ?
    """, (pacote,))

    return cur.fetchall()


def fetch_bios_pendentes(conn, pacote):
    """Autores JÁ publicados cuja bio ainda não foi enviada ao Supabase.

    A publicação de autor é one-shot (`fetch_autores_pendentes` filtra por
    `status_publish = 0`), mas a bio é gerada muito depois — o autor entra no
    Supabase sem `descricao` e nunca mais é reenviado. Esta fila corrige isso.
    """

    cur = conn.cursor()

    cur.execute("""
        SELECT id, nome, slug, nacionalidade, descricao
        FROM autores
        WHERE status_publish     = 1
          AND status_publish_bio = 0
          AND descricao IS NOT NULL
          AND TRIM(descricao) <> ''
        LIMIT ?
    """, (pacote,))

    return cur.fetchall()


def fetch_relacoes(conn, autor_id_local):
    """Retorna supabase_id dos livros relacionados ao autor."""

    cur = conn.cursor()

    cur.execute("""
        SELECT l.supabase_id
        FROM livros_autores la
        JOIN livros l ON l.id = la.livro_id
        WHERE la.autor_id = ?
          AND l.supabase_id IS NOT NULL
    """, (autor_id_local,))

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


def upsert_autor(row, autores_url, headers):

    (local_id, nome, slug, nacionalidade, existing_supabase_id, descricao) = row

    now = datetime.utcnow().isoformat()

    # NÃO enviar status_publish: a tabela `autores` do Supabase não tem essa
    # coluna (colunas reais: id, nome, slug, nacionalidade, descricao, created_at).
    # Enviá-la fazia o PostgREST retornar 400 em TODO autor — nenhum era publicado
    # e o mark_published local nunca era atingido (publicação de autores travada
    # em todo o pipeline). A presença na tabela já significa "publicado" (só
    # autores publicados recebem upsert). Ver gotcha em scripts/CLAUDE.md.
    payload = {
        "nome":          nome,
        "slug":          slug,
        "nacionalidade": nacionalidade,
        "created_at":    now,
    }

    if descricao:
        payload["descricao"] = descricao

    return upsert(autores_url, payload, headers)


def upsert_bio(row, autores_url, headers):
    """Atualiza só os campos editoriais do autor já publicado.

    Sem `created_at` no payload de propósito: com `resolution=merge-duplicates`
    o PostgREST só sobrescreve as colunas enviadas, e mandar `created_at` aqui
    reescreveria a data de criação de todo autor re-sincronizado.
    """

    payload = {
        "nome":          row["nome"],
        "slug":          row["slug"],
        "nacionalidade": row["nacionalidade"],
        "descricao":     row["descricao"],
    }

    return upsert(autores_url, payload, headers)


def upsert_relacao(livro_supabase_id, autor_slug, livros_autores_url, headers, supabase_url):
    """Resolve autor_id via slug no Supabase e insere relação."""

    lookup_url = (
        f"{supabase_url}/rest/v1/autores"
        f"?slug=eq.{autor_slug}&select=id"
    )

    try:
        res = requests.get(lookup_url, headers=headers, timeout=TIMEOUT)
        data = res.json()

        if not data:
            log(f"Autor não encontrado no Supabase: {autor_slug}")
            return False

        autor_supabase_id = data[0]["id"]

    except Exception as e:
        log(f"LOOKUP AUTOR ERRO → {e}")
        return False

    now = datetime.utcnow().isoformat()

    payload = {
        "livro_id": livro_supabase_id,
        "autor_id": autor_supabase_id,
    }

    return upsert(livros_autores_url, payload, headers)


# =========================
# FLAG LOCAL
# =========================

def mark_published(conn, local_id, bio_enviada=False):

    cur = conn.cursor()

    cur.execute("""
        UPDATE autores
        SET status_publish     = 1,
            status_publish_bio = ?,
            updated_at         = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (1 if bio_enviada else 0, local_id))

    conn.commit()


def mark_bio_published(conn, local_id):

    cur = conn.cursor()

    cur.execute("""
        UPDATE autores
        SET status_publish_bio = 1,
            updated_at         = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (local_id,))

    conn.commit()


# =========================
# RUN
# =========================

def run(pacote=100):

    conn = get_conn()

    # Lê credenciais em runtime — garante que o sistema de env do main.py já executou
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
        "Prefer": "resolution=merge-duplicates,return=representation",
    }

    autores_url        = f"{supabase_url}/rest/v1/autores?on_conflict=slug"
    livros_autores_url = f"{supabase_url}/rest/v1/livros_autores?on_conflict=livro_id,autor_id"

    autores = fetch_autores_pendentes(conn, pacote)

    if not autores:
        log("Nenhum autor pendente para publicação.")
    else:
        inserted  = 0
        failed    = 0
        relacoes  = 0
        total     = len(autores)

        for i, row in enumerate(autores, start=1):

            if _interrupt.requested():
                log(f"[AUTORES] Interrupção solicitada — encerrando após {i - 1}/{total}.")
                break

            local_id = row["id"]
            slug     = row["slug"]

            ok = upsert_autor(row, autores_url, headers)

            if not ok:
                failed += 1
                log(f"[AUTORES][{i:03d}/{total:03d}] FALHA → {row['nome']}")
                continue

            # Publica relações livros_autores
            livros_rows = fetch_relacoes(conn, local_id)

            for livro_row in livros_rows:
                livro_supabase_id = livro_row["supabase_id"]
                upsert_relacao(livro_supabase_id, slug, livros_autores_url, headers, supabase_url)
                relacoes += 1

            # A bio já foi junto no payload quando existia — não precisa resync.
            mark_published(conn, local_id, bio_enviada=bool(row["descricao"]))
            inserted += 1
            log(f"[AUTORES][{i:03d}/{total:03d}] OK → {row['nome']}")

        log(f"Autores publicados: {inserted} | Relações: {relacoes} | Falhas: {failed}")

    # Resync das bios que chegaram DEPOIS do primeiro publish. Roda sempre,
    # inclusive quando não há autor novo — é justamente o caso em que o
    # backlog de bios se acumula.
    _resync_bios(conn, autores_url, headers, pacote)

    conn.close()


# =========================
# RESYNC — BIOS PÓS-PUBLICAÇÃO
# =========================

def _resync_bios(conn, autores_url, headers, pacote):
    """Envia ao Supabase a `descricao` de autores publicados sem bio.

    Idempotente: cada autor sincronizado recebe `status_publish_bio = 1` e sai
    da fila. Lote a lote até esvaziar (ou até interrupção do usuário).
    """

    enviados = falhas = 0

    while True:
        rows = fetch_bios_pendentes(conn, pacote)

        if not rows:
            break

        total = len(rows)
        enviados_lote = 0

        for i, row in enumerate(rows, start=1):

            if _interrupt.requested():
                log(f"[AUTORES][BIO] Interrupção solicitada — encerrando após {i - 1}/{total}.")
                log(f"[AUTORES][BIO] Bios sincronizadas: {enviados} | Falhas: {falhas}")
                return

            if upsert_bio(row, autores_url, headers):
                mark_bio_published(conn, row["id"])
                enviados_lote += 1
                enviados += 1
                log(f"[AUTORES][BIO][{i:03d}/{total:03d}] OK → {row['nome']}")
            else:
                falhas += 1
                log(f"[AUTORES][BIO][{i:03d}/{total:03d}] FALHA → {row['nome']}")

        # Guard anti-giro: as falhas mantêm status_publish_bio = 0 e voltariam
        # na próxima query. Sem progresso NESTE lote, para (ex: Supabase fora).
        if enviados_lote == 0:
            log("[AUTORES][BIO] Nenhuma bio sincronizada no lote — abortando resync.")
            break

    if enviados or falhas:
        log(f"[AUTORES][BIO] Bios sincronizadas: {enviados} | Falhas: {falhas}")


# =========================
# REPAIR — RELAÇÕES ÓRFÃS
# =========================

def run_repair_relacoes(livro_ids=None):
    """Re-sincroniza livros_autores no Supabase.

    - ``livro_ids=None`` (menu 30 / rede de segurança): re-sincroniza TODOS os
      autores publicados — backfill completo (~80 min).
    - ``livro_ids=[...]`` (autopilot): modo INCREMENTAL — sincroniza apenas as
      relações dos livros informados (recém-publicados desde o último reparo).
      Segundos em vez de minutos.

    Útil quando autores foram publicados antes dos seus livros terem supabase_id,
    deixando a junction table vazia (autores órfãos).
    """

    conn = get_conn()

    supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not supabase_key:
        log("[REPAIR_RELACOES] ERRO: NEXT_PUBLIC_SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não configurados.")
        conn.close()
        return

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }

    livros_autores_url = f"{supabase_url}/rest/v1/livros_autores?on_conflict=livro_id,autor_id"

    cur = conn.cursor()

    # ── Modo INCREMENTAL: só as relações dos livros informados ────────────────
    if livro_ids is not None:
        if not livro_ids:
            conn.close()
            log("[REPAIR_RELACOES] Incremental: nenhum livro novo — nada a sincronizar.")
            return
        placeholders = ",".join("?" * len(livro_ids))
        cur.execute(f"""
            SELECT l.supabase_id AS livro_sid, a.slug AS autor_slug
            FROM livros l
            JOIN livros_autores la ON la.livro_id = l.id
            JOIN autores a         ON a.id = la.autor_id
            WHERE l.id IN ({placeholders})
              AND l.status_publish = 1
              AND l.supabase_id IS NOT NULL
              AND a.status_publish = 1
              AND a.slug IS NOT NULL AND TRIM(a.slug) <> ''
        """, tuple(livro_ids))
        pares = cur.fetchall()
        total = len(pares)
        log(f"[REPAIR_RELACOES] Incremental: {len(livro_ids)} livro(s) novo(s) → {total} relação(ões)")

        relacoes = falhas = 0
        interrompido = False
        for i, par in enumerate(pares, 1):
            if _interrupt.requested():
                log(f"[REPAIR_RELACOES] Interrupção solicitada — encerrando após {i - 1}/{total} relações.")
                interrompido = True
                break
            ok = upsert_relacao(par["livro_sid"], par["autor_slug"],
                                livros_autores_url, headers, supabase_url)
            if ok:
                relacoes += 1
            else:
                falhas += 1

        conn.close()
        log(f"[REPAIR_RELACOES] {'Interrompido' if interrompido else 'Finalizado'} (incremental) | "
            f"Relações: OK={relacoes} | Falhas={falhas}")
        return

    # ── Modo COMPLETO: todos os autores publicados (backfill) ─────────────────
    cur.execute("SELECT id, slug FROM autores WHERE status_publish = 1")
    autores = cur.fetchall()

    total      = len(autores)
    relacoes   = 0
    falhas     = 0
    sem_livros = 0

    log(f"[REPAIR_RELACOES] {total} autores publicados para re-sincronização")

    interrompido = False
    for i, autor in enumerate(autores, 1):
        # Ctrl+C cooperativo: sai no próximo autor (ponto seguro) em vez de
        # rodar os 8k+ até o fim. Quando invocado fora do autopilot (menu 30),
        # o handler não está instalado e requested() é sempre False (no-op).
        if _interrupt.requested():
            log(f"[REPAIR_RELACOES] Interrupção solicitada — encerrando após {i - 1}/{total} autores.")
            interrompido = True
            break

        local_id   = autor["id"]
        slug       = autor["slug"]

        livros_rows = fetch_relacoes(conn, local_id)

        if not livros_rows:
            sem_livros += 1
            continue

        log(f"[REPAIR_RELACOES][{i:03d}/{total:03d}] {slug} → {len(livros_rows)} livro(s)")

        for livro_row in livros_rows:
            livro_supabase_id = livro_row["supabase_id"]
            ok = upsert_relacao(livro_supabase_id, slug, livros_autores_url, headers, supabase_url)
            if ok:
                relacoes += 1
            else:
                falhas += 1

    conn.close()

    log(f"[REPAIR_RELACOES] {'Interrompido' if interrompido else 'Finalizado'} | "
        f"Relações: OK={relacoes} | Falhas={falhas} | Sem livros publicados={sem_livros}")
