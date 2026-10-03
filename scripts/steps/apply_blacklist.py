"""
scripts/steps/apply_blacklist.py

Lê scripts/data/blacklist.json (gerado pelo agente auditor via Claude chat)
e despublica os livros identificados:
  - SQLite: is_publishable=0, status_publish=0
  - Supabase: PATCH is_publishable=false, status="blacklisted"

Uso:
    python scripts/steps/apply_blacklist.py [--dry-run]

Flags:
    --dry-run    Exibe o que seria feito sem aplicar nenhuma alteração

Idempotência (desde 2026-10-03)
-------------------------------
Cada entrada é aplicada UMA vez: `livros.blacklist_aplicada_em` é gravada só
depois do UPDATE local E do PATCH no Supabase, e entrada cujo livro já tem a
coluna é pulada. PATCH que falha deixa a coluna NULL e é retentado no passe
seguinte.

Antes, o G reaplicava o arquivo inteiro a cada passe. Medido nos logs
`pipeline_2026-09-19_07-21-14`, `…09-26_06-08-39` e `…10-03_06-56-31`: 2.264
entradas, 2.225 UPDATEs + 2.225 PATCHes, **31–35 min por passe**, sem nenhum
livro novo. E não era só custo: o UPDATE regravava `status_synopsis = 4` e
`status_categorize = 4`, desfazendo o `_recover` do `reprocess_blacklist`
(que zera os sentinelas e soma `qa_retry`). O livro recuperado voltava a 4 no
passe seguinte, era "recuperado" de novo e caía em quarentena ao bater
`MAX_QA_RETRY`. No `books.db` em 2026-10-03: 2.631 blacklistados, **2.631 em
quarentena**, 22 deles por max-retry (`qa_retry = 2`) — das 24 entradas com
causa recuperável, nenhuma se recuperou. Testes em
`tests/test_apply_blacklist_idempotente.py`.
"""

import os
import sys
import json
import argparse
import sqlite3
import requests
from datetime import datetime, timezone

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SCRIPTS_ROOT)
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from core.db import get_connection
from core.logger import log as _core_log

BLACKLIST_PATH = os.path.join(SCRIPTS_ROOT, "data", "blacklist.json")
REQUEST_TIMEOUT = 15
JA_APLICADA = "__ja_aplicada__"


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class _Logger:
    def info(self, msg):    _core_log(f"[BLACKLIST] {msg}")
    def warning(self, msg): _core_log(f"[BLACKLIST][WARN] {msg}")
    def error(self, msg):   _core_log(f"[BLACKLIST][ERRO] {msg}")

log = _Logger()


# ---------------------------------------------------------------------------
# Env / credenciais
# ---------------------------------------------------------------------------

def _load_env() -> tuple[str, str]:
    try:
        from dotenv import load_dotenv
        env_local = os.path.join(PROJECT_ROOT, ".env.local")
        if os.path.exists(env_local):
            load_dotenv(env_local)
        env_pipeline = os.path.join(SCRIPTS_ROOT, ".env")
        if os.path.exists(env_pipeline):
            load_dotenv(env_pipeline)
    except ImportError:
        pass
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return url, key


# ---------------------------------------------------------------------------
# Leitura da blacklist
# ---------------------------------------------------------------------------

def load_blacklist() -> list[dict]:
    """
    Lê blacklist.json e retorna apenas entradas com severity medium ou high.
    Valida campos obrigatórios (slug).
    """
    if not os.path.exists(BLACKLIST_PATH):
        log.error(f"blacklist.json não encontrado em: {BLACKLIST_PATH}")
        sys.exit(1)

    try:
        with open(BLACKLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        log.error(f"blacklist.json inválido: {e}")
        sys.exit(1)

    entries = data.get("entries", [])

    valid = []
    skipped_severity = 0
    skipped_missing = 0

    for e in entries:
        if not e.get("slug"):
            skipped_missing += 1
            continue
        if e.get("severity") not in ("medium", "high"):
            skipped_severity += 1
            continue
        valid.append(e)

    log.info(f"Blacklist carregada: {len(valid)} entradas válidas "
             f"({skipped_severity} ignoradas por severity=low/none, "
             f"{skipped_missing} sem slug)")
    return valid


# ---------------------------------------------------------------------------
# Despublicação — SQLite
# ---------------------------------------------------------------------------

def _despublish_sqlite(
    conn: sqlite3.Connection,
    slug: str,
    dry_run: bool,
    reason: str = "",
    severity: str = "",
    forcar: bool = False,
) -> str | None:
    """
    Localiza o livro pelo slug, aplica is_publishable=0 e status_publish=0.
    Persiste a CAUSA (blacklist_reason/severity) para o reprocessamento (WS5).
    Retorna o id local se encontrado, None caso contrário, ou JA_APLICADA se a
    entrada já foi aplicada num passe anterior (nada é regravado).
    `forcar=True` ignora o marcador: é para quem despublica um livro que está
    PUBLICADO agora (qa_remediation.demote_untitled_published), não para
    reaplicar o arquivo.
    """
    row = conn.execute(
        "SELECT id, blacklist_aplicada_em, blacklist_reason FROM livros WHERE slug = ?",
        (slug,)
    ).fetchone()

    if not row:
        log.warning(f"Slug não encontrado no SQLite: {slug} — pulando")
        return None

    local_id = row[0]
    if row[1] and not forcar:
        return JA_APLICADA
    if row[2] is not None and not forcar:
        # Já despublicado localmente num passe cujo PATCH falhou: só o PATCH é
        # retentado. Regravar os sentinelas aqui desfaria um _recover feito
        # pelo reprocess_blacklist no intervalo.
        return local_id

    if dry_run:
        log.info(f"  [DRY-RUN][SQLite] Despublicaria: {slug} (id={local_id}, causa={reason})")
        return local_id

    conn.execute(
        """UPDATE livros
           SET is_publishable    = 0,
               status_publish    = 0,
               status_synopsis   = 4,
               status_categorize = 4,
               blacklist_reason   = ?,
               blacklist_severity = ?,
               updated_at        = ?
           WHERE id = ?""",
        (reason or None, severity or None,
         datetime.now(timezone.utc).isoformat(), local_id)
    )
    conn.commit()
    return local_id


# ---------------------------------------------------------------------------
# Despublicação — Supabase
# ---------------------------------------------------------------------------

def _despublish_supabase(slug: str, supabase_url: str, key: str, dry_run: bool) -> bool:
    if not supabase_url or not key:
        log.warning("Credenciais Supabase não configuradas — skip PATCH")
        return False

    if dry_run:
        log.info(f"  [DRY-RUN][Supabase] PATCH is_publishable=false, status=blacklisted para slug={slug}")
        return True

    try:
        url = f"{supabase_url}/rest/v1/livros?slug=eq.{slug}"
        r = requests.patch(
            url,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={"is_publishable": False, "status": "blacklisted"},
            timeout=REQUEST_TIMEOUT,
        )
        ok = r.status_code in (200, 204)
        if not ok:
            log.warning(f"  [Supabase] PATCH {r.status_code}: {slug} — {r.text[:120]}")
        return ok
    except Exception as e:
        log.error(f"  [Supabase] Erro ao despublicar {slug}: {e}")
        return False


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> None:
    supabase_url, key = _load_env()
    if not supabase_url or not key:
        log.warning("NEXT_PUBLIC_SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não configuradas.")
        log.warning("Despublicação no Supabase será ignorada.")

    entries = load_blacklist()
    if not entries:
        log.info("Nenhuma entrada para processar.")
        return

    conn = get_connection()
    total = len(entries)
    ok_sqlite = ok_supabase = falhas = ja_aplicadas = 0

    log.info(f"=== APPLY BLACKLIST (total={total}, dry_run={dry_run}) ===")

    PROGRESS_INTERVAL = 25
    for i, entry in enumerate(entries, 1):
        slug     = entry["slug"]
        reason   = entry.get("reason", "—")
        severity = entry.get("severity", "—")

        local_id = _despublish_sqlite(conn, slug, dry_run, reason=reason, severity=severity)
        if local_id == JA_APLICADA:
            ja_aplicadas += 1
            continue
        if local_id:
            ok_sqlite += 1
        else:
            falhas += 1
            continue

        sup_ok = _despublish_supabase(slug, supabase_url, key, dry_run)
        if sup_ok:
            ok_supabase += 1
            if not dry_run:
                conn.execute(
                    "UPDATE livros SET blacklist_aplicada_em = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), local_id),
                )
                conn.commit()

        if i % PROGRESS_INTERVAL == 0 or i == total:
            log.info(f"[BLACKLIST] {i}/{total} processados | OK={ok_sqlite} falhas={falhas}")

    conn.close()

    log.info(f"\n=== RESULTADO ===")
    log.info(f"Total na blacklist : {total}")
    log.info(f"Já aplicadas antes : {ja_aplicadas}")
    log.info(f"SQLite despublicado: {ok_sqlite}")
    log.info(f"Supabase atualizado: {ok_supabase}")
    log.info(f"Não encontrados    : {falhas}")
    if dry_run:
        log.info("(dry-run — nenhuma alteração aplicada)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aplica blacklist do auditor: despublica livros no SQLite e Supabase"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Exibe ações sem aplicar alterações")
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    run(dry_run=args.dry_run)
