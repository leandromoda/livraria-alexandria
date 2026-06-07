#!/usr/bin/env python3
"""
Guard de fila para cowork.

Expõe is_queue_busy() para uso programático (autopilot.py) e também
funciona como script standalone chamado pelo cowork_autopilot.bat.

Detecta três estados de fila ocupada:
  1. Inputs não processados em data/cowork/ (aguardando o agente)
  2. Outputs aguardando import em data/cowork/
  3. Lotes em voo: input movido para processed_*/ pelo agente mas
     output ainda não gerado (o agente está processando ativamente).

NÃO é afetado por inputs órfãos arquivados pelo reclaim — esses vão
para processed_*/reclaimed/ (subdir), que este módulo ignora.
"""

import glob
import os
import re
import sys

COWORK = os.path.join("data", "cowork")
NUM_PAT = re.compile(r"(\d{3})_")


def _get_nums(pattern: str) -> set:
    """Retorna o conjunto de prefixos NNN encontrados nos arquivos do padrão."""
    nums = set()
    for fpath in glob.glob(pattern):
        m = NUM_PAT.match(os.path.basename(fpath))
        if m:
            nums.add(m.group(1))
    return nums


def is_queue_busy(cowork_dir: str = COWORK) -> tuple[bool, str]:
    """Verifica se há trabalho pendente em qualquer fase da fila cowork.

    Retorna (busy: bool, reason: str).
    busy=True se houver inputs pendentes, outputs aguardando import ou lotes
    em voo. busy=False quando a fila está completamente ociosa.

    O check de "em voo" examina apenas filhos diretos de processed_*/
    (não subdirs como processed_*/reclaimed/), de forma que inputs
    arquivados pelo reclaim não geram falso positivo.
    """
    C = cowork_dir

    # 1. Inputs aguardando o agente (na raiz de cowork/)
    syn_inputs  = _get_nums(os.path.join(C, "*_synopsis_input.json"))
    cat_inputs  = _get_nums(os.path.join(C, "*_categorize_input.json"))

    # 2. Outputs aguardando import (na raiz de cowork/)
    syn_outputs = _get_nums(os.path.join(C, "*_synopsis_output.json"))
    cat_outputs = _get_nums(os.path.join(C, "*_categorize_output.json"))

    # 3. Lotes em voo: input movido pelo AGENTE para processed_*/
    #    mas output ainda não gerado (nem em cowork/ nem em processed_*/).
    #    Usa glob de filhos diretos — processed_*/reclaimed/ não é varrido.
    proc_syn = _get_nums(os.path.join(C, "processed_synopsis",   "*_synopsis_input.json"))
    proc_cat = _get_nums(os.path.join(C, "processed_categorize", "*_categorize_input.json"))
    syn_done = _get_nums(os.path.join(C, "processed_synopsis",   "*_synopsis_output.json"))
    cat_done = _get_nums(os.path.join(C, "processed_categorize", "*_categorize_output.json"))

    syn_inflight = proc_syn - (syn_outputs | syn_done)
    cat_inflight = proc_cat - (cat_outputs | cat_done)

    reasons = []
    if syn_inputs:   reasons.append(f"{len(syn_inputs)} input(s) sinopse aguardando agente")
    if cat_inputs:   reasons.append(f"{len(cat_inputs)} input(s) categorize aguardando agente")
    if syn_outputs:  reasons.append(f"{len(syn_outputs)} output(s) sinopse aguardando import")
    if cat_outputs:  reasons.append(f"{len(cat_outputs)} output(s) categorize aguardando import")
    if syn_inflight: reasons.append(f"{len(syn_inflight)} lote(s) sinopse em voo (agente processando)")
    if cat_inflight: reasons.append(f"{len(cat_inflight)} lote(s) categorize em voo (agente processando)")

    return bool(reasons), "; ".join(reasons)


if __name__ == "__main__":
    busy, reason = is_queue_busy()
    if busy:
        print("Fila ocupada:", reason)
        sys.exit(1)
    print("Fila ociosa.")
    sys.exit(0)
