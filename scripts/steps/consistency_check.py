# ============================================================
# STEP — CONSISTENCY CHECK
# Livraria Alexandria
#
# Consulta o Supabase (dados publicados) e gera relatório JSON
# com inconsistências: livros sem ofertas, ofertas inativas,
# URLs afiliadas ausentes, sinopses suspeitas.
#
# Saída: scripts/data/cowork/YYYYMMDDHHMMSS_consistency.json
# ============================================================

import json
import os
import requests

from datetime import datetime
from pathlib import Path

from core.logger import log


# =========================
# CONFIG
# =========================

SUPABASE_URL = "https://ncnexkuiiuzwujqurtsa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5jbmV4a3VpaXV6d3VqcXVydHNhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTU0MTY2MCwiZXhwIjoyMDg1MTE3NjYwfQ.CacLDlVd0noDzcuVJnxjx3eMr7SjI_19rAsDZeQh6S8"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "cowork"

SINOPSE_MIN_CHARS = 80
SINOPSE_SUSPICIOUS_PATTERNS = [
    "lorem ipsum",
    "texto indisponível",
    "sem sinopse",
    "n/a",
    "null",
    "undefined",
]


# =========================
# HELPERS
# =========================

def _get(endpoint: str, params: dict = None) -> list:
    """Faz GET paginado no Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    all_rows = []
    limit = 1000
    offset = 0

    while True:
        p = {"limit": limit, "offset": offset, **(params or {})}
        resp = requests.get(url, headers={**HEADERS, "Range-Unit": "items"}, params=p, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < limit:
            break
        offset += limit

    return all_rows


# =========================
# CHECKS
# =========================

def _check_livros_sem_ofertas(livros_ids: set, ofertas: list) -> list:
    """Livros publicados sem nenhuma oferta ativa."""
    livros_com_oferta_ativa = {
        o["livro_id"] for o in ofertas if o.get("ativa") is True
    }
    return [
        lid for lid in livros_ids if lid not in livros_com_oferta_ativa
    ]


def _check_ofertas_inativas(ofertas: list) -> list:
    """Ofertas com ativa=false."""
    return [
        {
            "id": o["id"],
            "livro_id": o.get("livro_id"),
            "marketplace": o.get("marketplace"),
            "preco": o.get("preco"),
        }
        for o in ofertas
        if o.get("ativa") is False
    ]


def _check_sem_url_afiliada(ofertas: list) -> list:
    """Ofertas ativas com url_afiliada ausente ou vazia."""
    return [
        {
            "id": o["id"],
            "livro_id": o.get("livro_id"),
            "marketplace": o.get("marketplace"),
        }
        for o in ofertas
        if o.get("ativa") is True and not (o.get("url_afiliada") or "").strip()
    ]


def _check_sinopses_suspeitas(livros: list) -> list:
    result = []
    for l in livros:
        sinopse = (l.get("descricao") or "").strip()
        if not sinopse:
            result.append({
                "id": l["id"],
                "slug": l.get("slug"),
                "titulo": l.get("titulo"),
                "problema": "sinopse_ausente",
                "sinopse_preview": "",
            })
            continue

        length = len(sinopse)
        if length < SINOPSE_MIN_CHARS:
            result.append({
                "id": l["id"],
                "slug": l.get("slug"),
                "titulo": l.get("titulo"),
                "problema": "sinopse_curta",
                "sinopse_chars": length,
                "sinopse_preview": sinopse[:120],
            })
            continue

        sinopse_lower = sinopse.lower()
        for pat in SINOPSE_SUSPICIOUS_PATTERNS:
            if pat in sinopse_lower:
                result.append({
                    "id": l["id"],
                    "slug": l.get("slug"),
                    "titulo": l.get("titulo"),
                    "problema": f"padrao_suspeito:{pat}",
                    "sinopse_preview": sinopse[:120],
                })
                break

    return result


# =========================
# MAIN
# =========================

def run():
    log("[CONSISTENCY] Iniciando verificação de consistência…")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Buscar dados do Supabase ---
    log("[CONSISTENCY] Buscando livros publicados…")
    livros = _get("livros", {"select": "id,slug,titulo,descricao", "status_publish": "eq.1"})
    log(f"[CONSISTENCY] {len(livros)} livros publicados encontrados")

    log("[CONSISTENCY] Buscando ofertas…")
    ofertas = _get("ofertas", {"select": "id,livro_id,ativa,url_afiliada,marketplace,preco"})
    log(f"[CONSISTENCY] {len(ofertas)} ofertas encontradas")

    # --- Executar checks ---
    livros_ids = {l["id"] for l in livros}
    livros_por_id = {l["id"]: l for l in livros}

    ids_sem_oferta = _check_livros_sem_ofertas(livros_ids, ofertas)
    livros_sem_oferta = [
        {
            "id": lid,
            "slug": livros_por_id[lid].get("slug"),
            "titulo": livros_por_id[lid].get("titulo"),
        }
        for lid in ids_sem_oferta
        if lid in livros_por_id
    ]

    ofertas_inativas = _check_ofertas_inativas(ofertas)
    sem_url_afiliada = _check_sem_url_afiliada(ofertas)
    sinopses_suspeitas = _check_sinopses_suspeitas(livros)

    total_issues = (
        len(livros_sem_oferta)
        + len(ofertas_inativas)
        + len(sem_url_afiliada)
        + len(sinopses_suspeitas)
    )

    report = {
        "meta": {
            "generated_at": datetime.utcnow().isoformat(),
            "total_livros_publicados": len(livros),
            "total_ofertas": len(ofertas),
            "total_issues": total_issues,
        },
        "summary": {
            "livros_sem_oferta_ativa": len(livros_sem_oferta),
            "ofertas_inativas": len(ofertas_inativas),
            "ofertas_sem_url_afiliada": len(sem_url_afiliada),
            "sinopses_suspeitas": len(sinopses_suspeitas),
        },
        "livros_sem_oferta": livros_sem_oferta,
        "ofertas_inativas": ofertas_inativas,
        "ofertas_sem_url_afiliada": sem_url_afiliada,
        "sinopses_suspeitas": sinopses_suspeitas,
    }

    # --- Gravar arquivo ---
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    out_path = OUTPUT_DIR / f"{ts}_consistency.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log(f"[CONSISTENCY] Relatório salvo em: {out_path.name}")
    log(
        f"[CONSISTENCY] Resumo → "
        f"sem oferta: {len(livros_sem_oferta)} | "
        f"inativas: {len(ofertas_inativas)} | "
        f"sem URL: {len(sem_url_afiliada)} | "
        f"sinopses suspeitas: {len(sinopses_suspeitas)} | "
        f"total issues: {total_issues}"
    )

    return out_path
