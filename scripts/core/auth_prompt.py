# ============================================================
# CORE — pedido de credencial visível ao usuário
# Livraria Alexandria
#
# POR QUE EXISTE: o G roda desacompanhado por horas (o log de 2026-08-24 durou
# ~23 h). Quando um pré-voo detecta credencial ausente ou expirada, avisar no
# log não resolve nada — ninguém está lendo. A fase que falhou fica parada até
# alguém abrir o arquivo no dia seguinte.
#
# Este módulo abre a página onde a credencial se resolve e deixa o aviso em
# destaque no console.
#
# ⚠ TRÊS CUIDADOS, e cada um existe por um motivo:
#
# 1. NÃO BLOQUEIA. O G é multijanela e roda de madrugada; parar o pipeline
#    esperando um input que pode não vir custaria a noite inteira. Abre a
#    janela, grita no log, e o passe segue degradado.
#
# 2. UMA VEZ POR PROCESSO, POR SERVIÇO. O `_run_gargalo` roda em laço — sem
#    guarda, uma sessão de 23 h abriria dezenas de abas do mesmo endereço.
#
# 3. DESLIGÁVEL. `ABRIR_LOGIN=0` para execução headless/CI, onde abrir
#    navegador não faz sentido (e pode nem existir).
# ============================================================

import os
import webbrowser

from core.logger import log

_ja_pedido = set()


def habilitado() -> bool:
    return os.getenv("ABRIR_LOGIN", "1").strip() not in ("0", "false", "no")


def pedir(servico: str, url: str, motivo: str, como_resolver: str) -> bool:
    """Abre `url` no navegador e destaca o pedido no log. Não bloqueia.

    Retorna True se a janela foi aberta nesta chamada. Chamadas seguintes para
    o mesmo `servico` no mesmo processo só logam.
    """
    primeira = servico not in _ja_pedido
    _ja_pedido.add(servico)

    log("")
    log("=" * 68)
    log(f"  ⚠  CREDENCIAL NECESSÁRIA — {servico}")
    log(f"     {motivo}")
    log(f"     Como resolver: {como_resolver}")
    log("=" * 68)

    if not primeira:
        log(f"[AUTH] Janela de {servico} já foi aberta neste processo — não reabre.")
        return False

    if not habilitado():
        log(f"[AUTH] ABRIR_LOGIN=0 — não vou abrir o navegador. Endereço: {url}")
        return False

    try:
        webbrowser.open(url, new=2)
        log(f"[AUTH] Abri o navegador em: {url}")
        log("[AUTH] O pipeline SEGUE em modo degradado — resolva quando puder e "
            "a próxima janela já pega a credencial nova.")
        return True
    except Exception as e:
        # Sem navegador (headless, servidor): o endereço no log já serve.
        log(f"[AUTH] Não consegui abrir o navegador ({type(e).__name__}). "
            f"Acesse manualmente: {url}")
        return False


def resetar():
    """Só para os testes — zera a guarda de 'já pedido'."""
    _ja_pedido.clear()
