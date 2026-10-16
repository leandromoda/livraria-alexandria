# ============================================================
# STEP — VERIFICAR PRODUTO DO ML (ofertas já publicadas)
# Livraria Alexandria
#
# Relê, pela API de catálogo do ML, o produto de cada oferta publicada com link
# de produto (/p/MLB…) e aplica o portão de "produto diferente"
# (`marketplace_scraper._produto_diferente`). Reprovado volta para a BUSCA do ML
# sem preço; o monitor procura o produto certo, já com o portão novo.
#
# POR QUE ESTE STEP EXISTE
# ------------------------
# O portão novo só protege casamento NOVO. Oferta com link de produto não passa
# mais por ele: o monitor lê preço direto da página do produto. Medido em
# 2026-10-16 (amostra de 400 das 2.349 ofertas, classificada à mão): 11
# produtos errados (2,8%) — kit, pacote com "+", mangá, graphic novel, leitura
# graduada, outro livro com o título dentro — mostrando preço e foto de outra
# coisa em páginas indexáveis. Projeção: ~65 páginas (≈35–115).
#
# CONSEQUÊNCIA ACEITA
# -------------------
# Reprovar tira o preço, e livro sem preço sai do índice (`livroIndexavel`).
# É o certo: preço de outro produto é pior que preço nenhum. A página volta
# sozinha quando o monitor achar o produto certo — `preco_tentativa_em` e
# `ml_migracao_em` são zerados para ele entrar no topo da fila.
#
# One-shot por oferta: `ml_produto_verificado_em` carimba aprovado e reprovado.
# ============================================================

import argparse
import os
import re
from collections import Counter

from core.db import get_conn
from core.logger import log

POR_CICLO = int(os.getenv("VERIFICA_ML_POR_CICLO", "100"))

_PID = re.compile(r"/p/(MLB\d+)")

_PENDENTES = """
    FROM livros
    WHERE status_publish = 1
      AND offer_url LIKE '%mercadolivre.com.br/p/MLB%'
      AND ml_produto_verificado_em IS NULL
"""


def decidir(titulo, autor, produto):
    """Motivo (str) para reprovar o produto da oferta, ou None se ele confere.

    Pura (sem rede): `produto` é o JSON de /products/{id}.
    """
    from core.ml_api import _autor_confere
    from steps.marketplace_scraper import _produto_diferente

    attrs = {a.get("id"): a.get("value_name") for a in (produto.get("attributes") or [])}
    titulo_ml = attrs.get("BOOK_TITLE") or produto.get("name") or ""
    # Só autor que DIVERGE reprova; indeterminado (sem AUTHOR) não.
    if autor and _autor_confere(autor, attrs.get("AUTHOR")) is False:
        return "autor diverge"
    return _produto_diferente(titulo, titulo_ml, produto.get("name"))


def _devolver_para_busca(conn, livro_id, consulta):
    from steps.offer_resolver import build_mercadolivre_url
    conn.execute(
        """
        UPDATE livros
        SET offer_url                = ?,
            marketplace              = 'mercado_livre',
            preco_atual              = NULL,
            preco_tentativa_em       = NULL,
            ml_migracao_em           = NULL,
            status_publish_oferta    = 0,
            ml_produto_verificado_em = CURRENT_TIMESTAMP,
            updated_at               = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (build_mercadolivre_url(consulta), livro_id),
    )


def run(limite=None, dry_run=False):
    """Verifica até `limite` ofertas. Devolve quantas foram reprovadas."""
    from core import ml_api

    limite = POR_CICLO if limite is None else limite
    if limite <= 0:
        return 0
    if not ml_api.configurado():
        log("[VERIFICA_ML] Sem ML_CLIENT_ID/ML_CLIENT_SECRET — pulando.")
        return 0

    conn = get_conn()
    restam = conn.execute(f"SELECT COUNT(*) {_PENDENTES}").fetchone()[0]
    if not restam:
        conn.close()
        return 0
    rows = conn.execute(
        f"SELECT id, titulo, autor, offer_url, lookup_query {_PENDENTES} LIMIT ?", (limite,)
    ).fetchall()

    tk = ml_api.token()
    aprovados = 0
    motivos = Counter()
    for livro_id, titulo, autor, url, lookup in rows:
        pid = _PID.search(url or "")
        if not pid:
            continue
        try:
            produto = ml_api._get_avaliado(f"{ml_api.API}/products/{pid.group(1)}", tk, vazio={})
        except ml_api.LimiteML:
            log("[VERIFICA_ML] Limite da API do ML — lote parado; retoma no próximo ciclo.")
            break
        except ml_api.ErroAPIML:
            continue            # não avaliou: não carimba
        motivo = decidir(titulo, autor, produto) if produto else None
        if motivo:
            motivos[motivo] += 1
            attrs = {a.get("id"): a.get("value_name") for a in (produto.get("attributes") or [])}
            log(f"[VERIFICA_ML] REPROVADO ({motivo}): {titulo} -> "
                f"{attrs.get('BOOK_TITLE') or produto.get('name')}")
            if not dry_run:
                _devolver_para_busca(conn, livro_id,
                                     (lookup or f"{titulo} {autor or ''} livro").strip())
        else:
            aprovados += 1
            if not dry_run:
                conn.execute("UPDATE livros SET ml_produto_verificado_em = CURRENT_TIMESTAMP "
                             "WHERE id = ?", (livro_id,))
        if not dry_run:
            conn.commit()

    reprovados = sum(motivos.values())
    log(f"[VERIFICA_ML] conferidos={aprovados + reprovados} | ok={aprovados} | "
        f"reprovados={reprovados} {dict(motivos) if motivos else ''} | "
        f"restam={restam - (0 if dry_run else aprovados + reprovados)}"
        + (" (dry-run)" if dry_run else ""))
    conn.close()
    return reprovados


if __name__ == "__main__":
    # No G quem carrega o .env é o main.py; aqui, rodando avulso, carrega-se.
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    p = argparse.ArgumentParser(description="Reverifica o produto do ML das ofertas publicadas")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args()
    run(limite=a.limit, dry_run=a.dry_run)
