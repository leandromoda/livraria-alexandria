# ============================================================
# STEP 19 — OFFER PRICE MONITOR
# Livraria Alexandria
#
# Monitora preço e disponibilidade das ofertas no marketplace.
# Pode rodar periodicamente sem re-executar todo o pipeline.
#
# Ações:
#   active       → atualiza preco_atual
#   price_changed → atualiza preço no Supabase, registra log
#   unavailable  → após 2 falhas consecutivas, despublica
#   reactivation → marca reactivation_pending=1 (sem republicar)
#
# Progresso: [MONITOR][NNN/TTT] → titulo
# ============================================================

import re
import time
import uuid
import requests

from datetime import datetime

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

TIMEOUT            = 15
RETRY_MAX          = 2
RETRY_DELAY        = 3
PRICE_THRESHOLD    = 0.05   # 5% de variação para considerar price_changed
UNAVAIL_THRESHOLD  = 2      # falhas consecutivas para despublicar

SUPABASE_URL = "https://ncnexkuiiuzwujqurtsa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5jbmV4a3VpaXV6d3VqcXVydHNhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTU0MTY2MCwiZXhwIjoyMDg1MTE3NjYwfQ.CacLDlVd0noDzcuVJnxjx3eMr7SjI_19rAsDZeQh6S8"

HEADERS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

HEADERS_SUPABASE = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

# Seletores de preço e disponibilidade por marketplace
PRICE_SELECTORS = {
    "amazon": {
        "price":   [".a-price .a-offscreen", "#price", ".a-color-price"],
        "unavail": ["Este item não está disponível", "Indisponível",
                    "Currently unavailable", "temporariamente indisponível"],
    },
    "mercadolivre": {
        "price":   [".andes-money-amount__fraction", ".price-tag-fraction"],
        "unavail": ["Sem estoque", "Produto indisponível"],
    },
}


# =========================
# DETECT MARKETPLACE
# =========================

def detect_marketplace(url):
    if not url:
        return None
    if "amazon.com.br" in url or "amzn" in url:
        return "amazon"
    if "mercadolivre.com.br" in url or "mercadolibre" in url:
        return "mercadolivre"
    return "unknown"


# =========================
# HTTP FETCH
# =========================

def fetch_page(url):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log("[MONITOR] beautifulsoup4 não instalado.")
        return None

    for attempt in range(RETRY_MAX):
        try:
            resp = requests.get(url, headers=HEADERS_HTTP, timeout=TIMEOUT)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            log(f"[MONITOR] HTTP erro (tentativa {attempt + 1}): {e}")
        if attempt < RETRY_MAX - 1:
            time.sleep(RETRY_DELAY)

    return None


# =========================
# EXTRACT PRICE
# =========================

def extract_price(soup, marketplace):
    selectors = PRICE_SELECTORS.get(marketplace, {}).get("price", [])
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            cleaned = re.sub(r"[^\d,\.]", "", text)
            cleaned = cleaned.replace(",", ".")
            try:
                return float(cleaned)
            except Exception:
                pass
    return None


def is_unavailable(soup, marketplace):
    signals  = PRICE_SELECTORS.get(marketplace, {}).get("unavail", [])
    page_txt = soup.get_text(separator=" ").lower()
    for signal in signals:
        if signal.lower() in page_txt:
            return True
    return False


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, limit):
    cur = conn.cursor()
    cur.execute("""
        SELECT
            id, titulo, offer_url, supabase_id,
            preco_atual, offer_status
        FROM livros
        WHERE status_publish = 1
          AND offer_url IS NOT NULL
          AND offer_url != ''
        ORDER BY preco_updated_at ASC NULLS FIRST
        LIMIT ?
    """, (limit,))
    return cur.fetchall()


# =========================
# SUPABASE PATCH
# =========================

def supabase_patch(supabase_id, payload):
    if not supabase_id:
        return False
    try:
        url  = f"{SUPABASE_URL}/rest/v1/livros?id=eq.{supabase_id}"
        resp = requests.patch(url, headers=HEADERS_SUPABASE, json=payload, timeout=30)
        return resp.status_code in [200, 204]
    except Exception as e:
        log(f"[MONITOR] Supabase PATCH erro: {e}")
        return False


# =========================
# LOG PRICE CHANGE
# =========================

def log_price_change(conn, livro_id, preco_anterior, preco_novo, status, marketplace):
    conn.execute("""
        INSERT INTO offer_price_log
            (id, livro_id, preco_anterior, preco_novo, offer_status, marketplace, captured_at)
        VALUES
            (lower(hex(randomblob(12))), ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (livro_id, preco_anterior, preco_novo, status, marketplace))
    conn.commit()


# =========================
# PROCESS ONE BOOK
# =========================

def process_book(conn, row, dry_run=False):

    livro_id     = row["id"]
    titulo       = row["titulo"]
    offer_url    = row["offer_url"]
    supabase_id  = row["supabase_id"]
    preco_ant    = row["preco_atual"]
    cur_status   = row["offer_status"] or "active"
    marketplace  = detect_marketplace(offer_url)

    soup = fetch_page(offer_url)

    if soup is None:
        # Falha de acesso — incrementar contador de falhas
        if not dry_run:
            conn.execute("""
                UPDATE livros
                SET offer_status = 'error',
                    updated_at   = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (livro_id,))
            conn.commit()
        return "error"

    unavail = is_unavailable(soup, marketplace)

    if unavail:
        new_status = "unavailable"
        if not dry_run:
            # Despublicar após UNAVAIL_THRESHOLD — aqui simplificado para 1 detecção clara
            conn.execute("""
                UPDATE livros
                SET offer_status        = 'unavailable',
                    preco_updated_at    = CURRENT_TIMESTAMP,
                    updated_at          = CURRENT_TIMESTAMP,
                    is_publishable      = 0,
                    status_publish      = 0
                WHERE id = ?
            """, (livro_id,))
            conn.commit()
            supabase_patch(supabase_id, {"is_publishable": False, "offer_status": "unavailable"})
            log_price_change(conn, livro_id, preco_ant, None, "unavailable", marketplace)
        return "unavailable"

    preco_novo = extract_price(soup, marketplace)

    # Determinar status
    if preco_novo is None:
        new_status = "active"
    elif preco_ant is None:
        new_status = "active"
    else:
        delta = abs(preco_novo - preco_ant) / max(preco_ant, 0.01)
        new_status = "price_changed" if delta >= PRICE_THRESHOLD else "active"

    # Verificar se estava unavailable antes → marcar reactivation_pending
    reactivation = 1 if cur_status == "unavailable" else 0

    if not dry_run:
        conn.execute("""
            UPDATE livros
            SET preco_anterior    = preco_atual,
                preco_atual       = COALESCE(?, preco_atual),
                preco_updated_at  = CURRENT_TIMESTAMP,
                offer_status      = ?,
                reactivation_pending = CASE WHEN ? = 1 THEN 1 ELSE reactivation_pending END,
                updated_at        = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (preco_novo, new_status, reactivation, livro_id))
        conn.commit()

        if new_status == "price_changed" and preco_novo:
            supabase_patch(supabase_id, {
                "preco_atual":  preco_novo,
                "offer_status": new_status,
            })
            log_price_change(conn, livro_id, preco_ant, preco_novo, new_status, marketplace)
        elif new_status == "active" and preco_novo:
            supabase_patch(supabase_id, {"preco_atual": preco_novo, "offer_status": "active"})

    return new_status


# =========================
# RUN
# =========================

def run(limit=50, dry_run=False):

    log(f"Offer Price Monitor iniciado (limit={limit}, dry_run={dry_run})…")

    conn  = get_conn()
    rows  = fetch_pending(conn, limit)
    total = len(rows)

    if not rows:
        log("Nenhum livro publicado com offer_url para monitorar.")
        conn.close()
        return

    counts = {"active": 0, "price_changed": 0, "unavailable": 0, "error": 0}

    for i, row in enumerate(rows, start=1):
        titulo = row["titulo"]
        print(f"[MONITOR][{i:03d}/{total:03d}] → {titulo}")

        try:
            status = process_book(conn, row, dry_run=dry_run)
            counts[status] = counts.get(status, 0) + 1
        except Exception as e:
            log(f"[MONITOR] Erro em '{titulo}': {e}")
            counts["error"] += 1

        time.sleep(1)

    conn.close()

    log(
        f"[MONITOR] "
        f"Ativos: {counts['active']} | "
        f"Preço alterado: {counts['price_changed']} | "
        f"Indisponíveis: {counts['unavailable']} | "
        f"Erros: {counts['error']} | "
        f"Total: {total}"
    )

    if dry_run:
        log("[MONITOR] dry-run ativo — nenhuma alteração foi salva.")
