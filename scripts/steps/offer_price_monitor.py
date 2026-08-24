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

import time
import requests

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

PRICE_THRESHOLD    = 0.05   # 5% de variação para considerar price_changed
UNAVAIL_THRESHOLD  = 2      # falhas consecutivas para despublicar

SUPABASE_URL = "https://ncnexkuiiuzwujqurtsa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5jbmV4a3VpaXV6d3VqcXVydHNhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTU0MTY2MCwiZXhwIjoyMDg1MTE3NjYwfQ.CacLDlVd0noDzcuVJnxjx3eMr7SjI_19rAsDZeQh6S8"

# ⚠ O HTTP de scraping vive em `marketplace_scraper` (pool de User-Agents,
# backoff de 503, circuit breaker). Este módulo tinha TIMEOUT/RETRY/HEADERS
# próprios e um `fetch_page` paralelo, removidos em 2026-08-23 — duas
# configurações de scraping divergindo era como o monitor acabou sem o backoff
# de 503 que o scraper já tinha.

HEADERS_SUPABASE = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
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
# RESOLUÇÃO DO PRODUTO
# =========================

# ⚠ Até 2026-08-23 este módulo tinha PRICE_SELECTORS próprios (seletores de
# PÁGINA DE PRODUTO) e os aplicava direto sobre `offer_url` — que é uma URL de
# BUSCA em 4.849 dos 4.856 livros publicados (99,9%, medido no books.db em
# 2026-08-23). O efeito é que `select_one('.a-price .a-offscreen')` devolvia o
# preço do PRIMEIRO CARD da busca, de qualquer item que estivesse lá.
#
# Amostra do mesmo dia (n=3 buscas reais, 2 utilizáveis — a terceira esgotou os
# 3 retries em 503): a busca de "O Guia do Mochileiro das Galáxias" devolveu 4
# preços — R$ 45,83 / 76,97 / 33,45 / 19,00 — e dois deles eram de OUTROS livros
# da série ("A vida, o universo e tudo mais", "Praticamente Inofensiva").
#
# Hoje a leitura é em 2 saltos (busca → página do produto), reusando
# `marketplace_scraper._resolve_produto`, com `estrito=True`: exige todos os
# tokens significativos do título no card e o sobrenome do autor no texto dele.
# SEM fallback de raspar a busca — dado de produto errado é pior que dado
# nenhum. Ver TASK-OFERTAS-004.

def resolve_produto(offer_url, titulo, autor=None):
    """(preco, disponivel, url_afiliada_do_produto) ou (None, None, None).

    `url_afiliada` só volta preenchida quando a resolução partiu de uma URL de
    busca — é o deep-link que substitui a busca no `offer_url` do livro.
    """
    from steps.marketplace_scraper import _resolve_produto, scrape_marketplace

    if _e_url_de_busca(offer_url):
        result, afiliada = _resolve_produto(offer_url, titulo, autor, estrito=True)
        if not result:
            return None, None, None
        return result.get("preco"), result.get("disponivel"), afiliada

    # `offer_url` já é página de produto (livros que passaram pelo deep-link, ou
    # os 7 /dp/ legados): lê direto, sem o salto da busca.
    result = scrape_marketplace(offer_url)
    if not result:
        return None, None, None
    return result.get("preco"), result.get("disponivel"), None


def _e_url_de_busca(url):
    """URL de listagem/busca, em oposição à página de um produto."""
    u = (url or "").lower()
    return ("/s?k=" in u or "/s/?k=" in u
            or "lista.mercadolivre" in u or "/search" in u)


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, limit):
    """Fila do monitor: COBERTURA antes de refresh.

    Quem nunca teve preço vem primeiro; só depois o round-robin por
    `preco_updated_at`. Medido em 2026-08-23: 553 dos 4.856 publicados (11%)
    já tinham sido visitados, e 219 desses ficaram com preço — revisitar quem
    já tem preço antes de cobrir os 89% restantes é desperdício de um step
    que é o mais lento do passe não-LLM.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT
            id, titulo, autor, slug, offer_url, supabase_id,
            preco_atual, offer_status
        FROM livros
        WHERE status_publish = 1
          AND offer_url IS NOT NULL
          AND offer_url != ''
        ORDER BY (preco_atual IS NOT NULL) ASC,
                 preco_updated_at ASC NULLS FIRST
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


def supabase_patch_oferta(supabase_id, payload):
    """PATCH na tabela ofertas filtrando por livro_id."""
    if not supabase_id:
        return False
    try:
        url  = f"{SUPABASE_URL}/rest/v1/ofertas?livro_id=eq.{supabase_id}"
        resp = requests.patch(url, headers=HEADERS_SUPABASE, json=payload, timeout=30)
        return resp.status_code in [200, 204]
    except Exception as e:
        log(f"[MONITOR] Supabase PATCH oferta erro: {e}")
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
    autor        = (row["autor"] if "autor" in row.keys() else None)
    offer_url    = row["offer_url"]
    supabase_id  = row["supabase_id"]
    preco_ant    = row["preco_atual"]
    cur_status   = row["offer_status"] or "active"
    marketplace  = detect_marketplace(offer_url)

    preco_novo, disponivel, url_produto = resolve_produto(offer_url, titulo, autor)

    if preco_novo is None and disponivel is None:
        # Não chegamos à página do produto: bot wall, timeout, ou nenhum card
        # compatível na busca.
        #
        # ⚠ NÃO gravar `preco_updated_at` aqui. Até 2026-08-23 o UPDATE de
        # sucesso rodava mesmo sem preço, então o livro ia para o fim da fila
        # como se tivesse sido resolvido e só voltaria depois de o monitor
        # passear pelos outros 4.855. `offer_status='error'` é o estado certo:
        # `publish_ofertas.fix_offer_status` já o recicla para 1 no passe
        # seguinte, sem perder a offer_url.
        if not dry_run:
            conn.execute("""
                UPDATE livros
                SET offer_status = 'error',
                    updated_at   = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (livro_id,))
            conn.commit()
        return "error"

    if url_produto and url_produto != offer_url and not dry_run:
        # Promove o deep-link: o usuário passa a cair no produto cujo preço está
        # exibido, em vez de numa página de busca. A propagação ao Supabase é
        # automática — `publish_ofertas._payload_hash` inclui `url_afiliada` e
        # `preco`, então o `run_repair` do mesmo passe do G republica sozinho.
        conn.execute("""
            UPDATE livros
            SET offer_url  = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (url_produto, livro_id))
        conn.commit()

    if disponivel is False:
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
            supabase_patch_oferta(supabase_id, {"ativa": False})
            log_price_change(conn, livro_id, preco_ant, None, "unavailable", marketplace)
        return "unavailable"

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
            supabase_patch_oferta(supabase_id, {"preco": preco_novo})
            log_price_change(conn, livro_id, preco_ant, preco_novo, new_status, marketplace)
        elif new_status == "active" and preco_novo:
            supabase_patch(supabase_id, {"preco_atual": preco_novo, "offer_status": "active"})
            supabase_patch_oferta(supabase_id, {"preco": preco_novo, "ativa": True})
        elif new_status == "active" and reactivation:
            # Reativação sem preço novo conhecido — garante ativa=True
            supabase_patch_oferta(supabase_id, {"ativa": True})

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
    results = []

    for i, row in enumerate(rows, start=1):
        titulo = row["titulo"]
        print(f"[MONITOR][{i:03d}/{total:03d}] → {titulo}")

        try:
            status = process_book(conn, row, dry_run=dry_run)
            counts[status] = counts.get(status, 0) + 1
        except Exception as e:
            log(f"[MONITOR] Erro em '{titulo}': {e}")
            counts["error"] += 1
            status = "error"

        results.append({
            "titulo": titulo,
            "slug": (row["slug"] if "slug" in row.keys() else None),
            "status": status,
        })

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

    # Relatório padronizado para o /audit. Só lista os não-ativos (acionáveis):
    # indisponíveis (despublicar/desativar oferta) e erros (revisar scraper).
    from core.audit_report import save_audit_report
    report = {
        "mode": "prices",
        "total": total,
        "dry_run": dry_run,
        "summary": counts,
        "results": [r for r in results if r["status"] != "active"],
    }
    path = save_audit_report(report)
    log(f"[MONITOR] Relatório salvo: {path}")
    return report
