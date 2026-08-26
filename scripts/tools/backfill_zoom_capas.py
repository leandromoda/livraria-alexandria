# ============================================================
# BACKFILL — zoom das capas do Google Books
# Livraria Alexandria
#
# Reescreve `livros.imagem_url` das capas do books.google.com para
# `zoom=COVERS.ZOOM_GOOGLE_BOOKS`, no SQLite E no Supabase.
#
# POR QUE EXISTE (medido em 2026-08-26 no books.db):
#   `covers.fetch_google_cover` fazia `replace("&zoom=1", "&zoom=0")` com o
#   comentario "remove zoom baixo". zoom=0 e a resolucao CHEIA. Resultado:
#   1.294 das 2.137 capas do Google Books (60%) — 28% de todas as 4.609 capas
#   publicadas — servindo centenas de KB para exibir 176x256 px, e a capa tem
#   `priority` no BookCover.tsx, ou seja, e o elemento de LCP da pagina.
#
#   Medido na capa de `o-jardim-das-rosas`:
#     zoom=0 (antes) -> 593 KB / 1,56 s
#     zoom=2 (hoje)  ->  40 KB / 0,96 s
#     zoom=1         ->  24 KB / 0,39 s
#
# POR QUE TAMBEM PRECISA DO SUPABASE:
#   `publish.fetch_pendentes` filtra por `status_publish = 0` — cada livro e
#   enviado UMA vez. Mudar so o SQLite nunca chegaria ao site. Mesmo gotcha ja
#   documentado para as bios de autor (`publish_autores._resync_bios`).
#
# Uso:
#   python tools/backfill_zoom_capas.py --dry-run
#   python tools/backfill_zoom_capas.py
#   python tools/backfill_zoom_capas.py --limite 50
#
# Idempotente: so toca em quem esta fora do zoom alvo. Interrompivel (Ctrl+C).
# ============================================================

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

from core.db import get_conn
from core.logger import log
from steps.covers import ZOOM_GOOGLE_BOOKS, normalizar_capa_google

# Credenciais reusadas de `steps.publish` de propósito: elas já vivem lá (e em
# publish_autores/publish_ofertas), e este arquivo escreve na MESMA tabela.
# Copiar a chave para cá seria a quarta cópia da mesma string no repositório.
from steps.publish import SUPABASE_URL, SUPABASE_KEY  # noqa: E402

TIMEOUT = 30


def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _patch_supabase(supabase_id, url):
    """PATCH de UMA coluna. Retorna True/False."""
    try:
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/livros?id=eq.{supabase_id}",
            headers=_headers(), json={"imagem_url": url}, timeout=TIMEOUT)
        return resp.status_code in (200, 204)
    except Exception as e:
        log(f"[ZOOM] Supabase PATCH erro: {e}")
        return False


def fetch_pendentes(conn, limite=None):
    """Capas do Google Books fora do zoom alvo.

    O filtro `NOT LIKE '%zoom=<alvo>%'` deixa a ferramenta idempotente: rodar
    duas vezes nao reenvia nada.
    """
    cur = conn.cursor()
    sql = f"""
        SELECT id, slug, imagem_url, supabase_id, status_publish
        FROM livros
        WHERE imagem_url LIKE '%books.google.com%'
          AND (imagem_url NOT LIKE '%zoom={ZOOM_GOOGLE_BOOKS}%'
               OR imagem_url LIKE 'http://%')
        ORDER BY status_publish DESC, slug
    """
    if limite:
        sql += f" LIMIT {int(limite)}"
    cur.execute(sql)
    return cur.fetchall()


def run(limite=None, dry_run=False):
    conn = get_conn()
    rows = fetch_pendentes(conn, limite)

    publicados = sum(1 for r in rows if r["status_publish"] == 1)
    log(f"[ZOOM] capas do Google Books fora de zoom={ZOOM_GOOGLE_BOOKS}: "
        f"{len(rows)} ({publicados} publicadas) | dry_run={dry_run}")

    if not rows:
        conn.close()
        return 0, 0, 0

    n_local = n_remoto = n_falha = 0
    cur = conn.cursor()

    for i, row in enumerate(rows, start=1):
        nova = normalizar_capa_google(row["imagem_url"])
        if nova == row["imagem_url"]:
            continue

        if dry_run:
            if i <= 5:
                log(f"[ZOOM][{i}] {row['slug']}")
                log(f"         antes: {row['imagem_url'][:96]}")
                log(f"         depois: {nova[:96]}")
            n_local += 1
            continue

        try:
            cur.execute(
                "UPDATE livros SET imagem_url = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?", (nova, row["id"]))
            conn.commit()
            n_local += 1

            # So o que esta no site precisa de PATCH; o resto vai junto no
            # publish, que ainda nao aconteceu para ele.
            if row["status_publish"] == 1 and row["supabase_id"]:
                if _patch_supabase(row["supabase_id"], nova):
                    n_remoto += 1
                else:
                    n_falha += 1
                    log(f"[ZOOM][{i:04d}/{len(rows):04d}] FALHA no Supabase → {row['slug']}")

            if i % 100 == 0:
                log(f"[ZOOM][{i:04d}/{len(rows):04d}] local={n_local} "
                    f"supabase={n_remoto} falhas={n_falha}")
        except KeyboardInterrupt:
            log(f"[ZOOM] Interrompido em {i}/{len(rows)}. "
                f"Reexecutar retoma de onde parou (idempotente).")
            break

    conn.close()
    log(f"[ZOOM] Finalizado | SQLite: {n_local} | Supabase: {n_remoto} | Falhas: {n_falha}")
    return n_local, n_remoto, n_falha


def main():
    ap = argparse.ArgumentParser(
        description="Backfill do zoom das capas do Google Books")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limite", type=int, default=None)
    args = ap.parse_args()

    if not args.dry_run and not SUPABASE_KEY:
        log("[ZOOM] chave do Supabase ausente — o SQLite seria atualizado e o "
            "site NAO, deixando os dois fora de sincronia. Abortando.")
        sys.exit(1)

    run(limite=args.limite, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
