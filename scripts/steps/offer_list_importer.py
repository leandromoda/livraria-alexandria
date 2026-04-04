# ============================================================
# STEP 30 — OFFER LIST IMPORTER
# Livraria Alexandria
#
# Lê scripts/data/offer_list.json gerado pelo agente offer_finder,
# atualiza o banco SQLite local e publica as ofertas no Supabase.
#
# Fluxo:
#   1. Lê offer_list.json
#   2. Para cada livro, localiza o registro local pelo supabase_id
#   3. Atualiza SQLite: offer_url, marketplace, offer_status=1
#   4. Faz upsert de TODAS as ofertas (amazon + mercadolivre) no Supabase
#   5. Marca status_publish_oferta=1 no SQLite após sucesso
#
# Idempotente: re-executável sem duplicar ofertas no Supabase
#   (usa on_conflict=livro_id,marketplace com merge-duplicates).
# ============================================================

import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

_ENV_PATH   = Path(__file__).resolve().parents[1] / ".env"
_JSON_PATH  = Path(__file__).resolve().parents[1] / "data" / "offer_list.json"

load_dotenv(dotenv_path=_ENV_PATH)

TIMEOUT     = 60
MAX_RETRIES = 3

# Marketplace preferido ao persistir no campo único do SQLite
# (o outro marketplace ainda é publicado direto no Supabase)
MARKETPLACE_PRIORITY = ["amazon", "mercadolivre"]


# =========================
# LOAD JSON
# =========================

def load_offer_list(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"offer_list.json não encontrado em: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    livros = data.get("livros", [])
    meta   = data.get("meta", {})

    log(f"[IMPORTER] offer_list.json carregado: {len(livros)} livros | "
        f"{meta.get('total_ofertas', '?')} ofertas | gerado em {meta.get('gerado_em', '?')}")

    return data


# =========================
# SQLITE — LOOKUP
# =========================

def find_local_id(conn, supabase_id: str) -> str | None:
    """Retorna o id local (SQLite) dado um supabase_id."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM livros WHERE supabase_id = ? LIMIT 1",
        (supabase_id,)
    )
    row = cur.fetchone()
    return row[0] if row else None


# =========================
# SQLITE — UPDATE PRIMARY OFFER
# =========================

def update_primary_offer(conn, local_id: str, offer: dict) -> None:
    """Persiste a oferta principal (maior confiança ou MARKETPLACE_PRIORITY) no registro SQLite."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE livros
        SET offer_url    = ?,
            marketplace  = ?,
            offer_status = 1,
            updated_at   = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (offer["url"], offer["marketplace"], local_id))
    conn.commit()


# =========================
# SQLITE — MARK PUBLISHED
# =========================

def mark_published(conn, local_id: str) -> None:
    cur = conn.cursor()
    cur.execute("""
        UPDATE livros
        SET status_publish_oferta = 1,
            updated_at            = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (local_id,))
    conn.commit()


# =========================
# SUPABASE — UPSERT
# =========================

def supabase_upsert(url: str, payload: dict, headers: dict) -> bool:
    for attempt in range(MAX_RETRIES):
        try:
            res = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=TIMEOUT,
            )

            if res.status_code == 409:
                return True  # já existe, ok

            if res.status_code not in (200, 201):
                log(f"[IMPORTER] Supabase erro {res.status_code} → {res.text[:200]}")
                time.sleep(2)
                continue

            return True

        except Exception as exc:
            log(f"[IMPORTER] Retry {attempt + 1}/{MAX_RETRIES} → {exc}")
            time.sleep(2)

    return False


# =========================
# PICK PRIMARY OFFER
# =========================

def pick_primary(ofertas: list[dict]) -> dict | None:
    """
    Seleciona a oferta principal para persistir no campo único do SQLite.
    Critérios em ordem:
      1. Maior confiança (high > medium > low)
      2. Marketplace prioritário (amazon > mercadolivre)
    """
    if not ofertas:
        return None

    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    marketplace_rank = {m: i for i, m in enumerate(MARKETPLACE_PRIORITY)}

    def sort_key(o):
        return (
            confidence_rank.get(o.get("confianca", "low"), 0),
            -marketplace_rank.get(o.get("marketplace", ""), 99),
        )

    return sorted(ofertas, key=sort_key, reverse=True)[0]


# =========================
# RUN
# =========================

def run(pacote: int = 500) -> None:

    # --- Credenciais ---
    supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not supabase_key:
        log("[IMPORTER] ERRO: NEXT_PUBLIC_SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não configurados.")
        return

    headers = {
        "apikey":        supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates,return=minimal",
    }
    ofertas_endpoint = f"{supabase_url}/rest/v1/ofertas?on_conflict=livro_id,marketplace"

    # --- Carregar JSON ---
    try:
        data = load_offer_list(_JSON_PATH)
    except FileNotFoundError as exc:
        log(f"[IMPORTER] {exc}")
        return

    livros = data.get("livros", [])

    if not livros:
        log("[IMPORTER] offer_list.json não contém livros.")
        return

    # Limita ao pacote (caso o arquivo seja grande)
    livros = livros[:pacote]

    conn = get_conn()
    now  = datetime.utcnow().isoformat()

    total_livros  = len(livros)
    ok_ofertas    = 0
    fail_ofertas  = 0
    skipped       = 0
    needs_review  = 0

    log(f"[IMPORTER] Processando {total_livros} livros...")

    for i, livro in enumerate(livros, start=1):

        supabase_id = livro.get("supabase_id")
        slug        = livro.get("slug", "?")
        titulo      = livro.get("titulo", slug)
        ofertas     = livro.get("ofertas", [])
        status      = livro.get("status", "not_found")

        prefix = f"[IMPORTER][{i:03d}/{total_livros:03d}]"

        # --- Sem ofertas ---
        if status == "not_found" or not ofertas:
            log(f"{prefix} SKIP (not_found) → {titulo}")
            skipped += 1
            continue

        # --- Localizar registro local ---
        local_id = find_local_id(conn, supabase_id)

        if not local_id:
            log(f"{prefix} AVISO: supabase_id {supabase_id} não encontrado no SQLite → {titulo}")
            skipped += 1
            continue

        # --- Atualizar SQLite com oferta principal ---
        primary = pick_primary(ofertas)
        if primary:
            update_primary_offer(conn, local_id, primary)

        # --- Publicar TODAS as ofertas no Supabase ---
        livro_ok = True

        for oferta in ofertas:
            marketplace = oferta.get("marketplace")
            url         = oferta.get("url")
            confianca   = oferta.get("confianca", "low")
            review_flag = oferta.get("needs_review", False)

            if not url or not marketplace:
                log(f"{prefix} SKIP oferta inválida (sem url/marketplace) → {titulo}")
                fail_ofertas += 1
                livro_ok = False
                continue

            if review_flag:
                needs_review += 1

            payload = {
                "livro_id":    supabase_id,
                "marketplace": marketplace,
                "url_afiliada": url,
                "preco":       None,          # preço será preenchido pelo price monitor
                "ativa":       not review_flag,  # low-confidence entra inativa para revisão
                "created_at":  now,
            }

            ok = supabase_upsert(ofertas_endpoint, payload, headers)

            if ok:
                ok_ofertas += 1
                flag = " [needs_review]" if review_flag else ""
                log(f"{prefix} OK → {titulo} ({marketplace}, {confianca}){flag}")
            else:
                fail_ofertas += 1
                livro_ok = False
                log(f"{prefix} FALHA → {titulo} ({marketplace})")

        # --- Marcar publicado no SQLite ---
        if livro_ok:
            mark_published(conn, local_id)

    conn.close()

    log("─" * 56)
    log(f"[IMPORTER] Concluído.")
    log(f"  Livros processados : {total_livros}")
    log(f"  Ofertas OK         : {ok_ofertas}")
    log(f"  Falhas             : {fail_ofertas}")
    log(f"  Pulados            : {skipped}")
    if needs_review:
        log(f"  Aguardando revisão : {needs_review} (confiança baixa — publicadas como inativas)")
