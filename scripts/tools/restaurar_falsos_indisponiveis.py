# ============================================================
# REPARO — livros despublicados por falso "indisponível"
# Livraria Alexandria
#
# POR QUE EXISTE: em 2026-08-29 o monitor de preços tirou 6 livros do ar numa
# passada. Os três conferidos na hora estavam à venda:
#
#     A Quinta Estação    R$  69,10
#     Cidade dos Ossos    R$ 300,90
#     Encontro com Rama   R$  54,85
#
# `marketplace_scraper.is_unavailable` varria o texto INTEIRO da página atrás
# das palavras de `unavail`, e casava com boilerplate que existe em toda página
# de produto da Amazon: `${cardName} indisponível para o vendedor escolhido`,
# `Imagem não disponível`, `Listar indisponível`. Nenhum fala do produto.
#
# A causa raiz está corrigida. Esta ferramenta desfaz o estrago acumulado.
#
# NÃO republica no escuro: reconsulta cada livro e só restaura o que a página
# mostrar como disponível AGORA. Quem estiver mesmo indisponível fica de fora.
#
# Uso:
#   python tools/restaurar_falsos_indisponiveis.py --dry-run
#   python tools/restaurar_falsos_indisponiveis.py
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
from steps.publish import SUPABASE_URL, SUPABASE_KEY

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


def _patch(caminho, filtro, payload):
    try:
        r = requests.patch(f"{SUPABASE_URL}/rest/v1/{caminho}?{filtro}",
                           headers=HEADERS, json=payload, timeout=30)
        return r.status_code in (200, 204)
    except Exception as e:
        log(f"[RESTAURA] PATCH {caminho} falhou: {e}")
        return False


def verificar(titulo, autor, offer_url, isbn=None):
    """(disponivel, preco). `disponivel=None` = não deu para verificar."""
    from steps.marketplace_scraper import scrape_marketplace, detect_marketplace
    from core import ml_api

    if detect_marketplace(offer_url) == "mercadolivre" and ml_api.configurado():
        achado = ml_api.buscar_livro(titulo, autor, isbn)
        if achado:
            return True, achado["preco"]

    res = scrape_marketplace(offer_url)
    if not res:
        return None, None
    return res.get("disponivel"), res.get("preco")


def run(dry_run=False):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, autor, isbn, slug, supabase_id, offer_url,
               status_publish, is_publishable
        FROM livros
        WHERE offer_status = 'unavailable'
        ORDER BY updated_at DESC
    """)
    linhas = cur.fetchall()
    log(f"[RESTAURA] {len(linhas)} livro(s) marcados 'unavailable' | dry_run={dry_run}")

    restaurados = confirmados = indefinidos = 0

    for i, r in enumerate(linhas, 1):
        disponivel, preco = verificar(r["titulo"], r["autor"], r["offer_url"], r["isbn"])

        if disponivel is None:
            indefinidos += 1
            log(f"[RESTAURA][{i:02d}/{len(linhas):02d}] ? {r['titulo'][:44]} "
                f"— não deu para verificar, deixando como está")
            continue

        if not disponivel:
            confirmados += 1
            log(f"[RESTAURA][{i:02d}/{len(linhas):02d}] ✓ {r['titulo'][:44]} "
                f"— indisponível DE VERDADE, mantido fora")
            continue

        restaurados += 1
        log(f"[RESTAURA][{i:02d}/{len(linhas):02d}] ↺ {r['titulo'][:44]} "
            f"— disponível (preço={preco}), restaurando")
        if dry_run:
            continue

        cur.execute("""
            UPDATE livros
            SET offer_status     = 1,
                is_publishable   = 1,
                status_publish   = 1,
                preco_atual      = COALESCE(?, preco_atual),
                updated_at       = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (preco, r["id"]))
        conn.commit()

        if r["supabase_id"]:
            _patch("livros", f"id=eq.{r['supabase_id']}",
                   {"is_publishable": True, "offer_status": "active"})
            payload = {"ativa": True}
            if preco:
                payload["preco"] = preco
            _patch("ofertas", f"livro_id=eq.{r['supabase_id']}", payload)

    conn.close()
    log(f"[RESTAURA] Restaurados: {restaurados} | Indisponíveis confirmados: "
        f"{confirmados} | Não verificáveis: {indefinidos}")
    return restaurados, confirmados, indefinidos


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Restaura livros despublicados por falso 'indisponível'")
    ap.add_argument("--dry-run", action="store_true")
    run(dry_run=ap.parse_args().dry_run)
