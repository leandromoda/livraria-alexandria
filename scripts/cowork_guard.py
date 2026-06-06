#!/usr/bin/env python3
"""
Guard de fila para cowork_autopilot.bat.

Sai com código 1 (fila ocupada) se houver qualquer trabalho pendente em data/cowork/:
  - inputs aguardando o agente (não processados ainda)
  - outputs aguardando import (agente terminou, import ainda não rodou)
  - lotes em voo: input já movido para processed_*/ pelo agente, mas output
    ainda não gravado — janela de overlap entre ciclos do Task Scheduler de 30 min.

Sai com código 0 (fila ociosa) somente quando TODAS as filas estão vazias.

Chamado por: scripts/cowork_autopilot.bat (passo [1/3])
"""

import glob
import os
import re
import sys

COWORK = "data/cowork"
NUM_PAT = re.compile(r"(\d{3})_")


def get_nums(pattern):
    """Retorna o conjunto de prefixos NNN encontrados nos arquivos do padrão."""
    nums = set()
    for fpath in glob.glob(pattern):
        m = NUM_PAT.match(os.path.basename(fpath))
        if m:
            nums.add(m.group(1))
    return nums


# Inputs não processados (agente ainda não os consumiu)
syn_inputs  = get_nums(f"{COWORK}/*_synopsis_input.json")
cat_inputs  = get_nums(f"{COWORK}/*_categorize_input.json")

# Outputs aguardando import
syn_outputs = get_nums(f"{COWORK}/*_synopsis_output.json")
cat_outputs = get_nums(f"{COWORK}/*_categorize_output.json")

# Lotes em voo: input já movido para processed_*/ mas output ainda não gerado
# (nem em data/cowork/ nem em processed_*/ — caso o import já tenha arquivado)
proc_syn = get_nums(f"{COWORK}/processed_synopsis/*_synopsis_input.json")
proc_cat = get_nums(f"{COWORK}/processed_categorize/*_categorize_input.json")
syn_done = get_nums(f"{COWORK}/processed_synopsis/*_synopsis_output.json")
cat_done = get_nums(f"{COWORK}/processed_categorize/*_categorize_output.json")

syn_inflight = proc_syn - (syn_outputs | syn_done)
cat_inflight = proc_cat - (cat_outputs | cat_done)

reasons = []
if syn_inputs:   reasons.append(f"{len(syn_inputs)} input(s) sinopse aguardando agente")
if cat_inputs:   reasons.append(f"{len(cat_inputs)} input(s) categorize aguardando agente")
if syn_outputs:  reasons.append(f"{len(syn_outputs)} output(s) sinopse aguardando import")
if cat_outputs:  reasons.append(f"{len(cat_outputs)} output(s) categorize aguardando import")
if syn_inflight: reasons.append(f"{len(syn_inflight)} lote(s) sinopse em voo (agente processando)")
if cat_inflight: reasons.append(f"{len(cat_inflight)} lote(s) categorize em voo (agente processando)")

if reasons:
    print("Fila ocupada:", "; ".join(reasons))
    sys.exit(1)

print("Fila ociosa.")
sys.exit(0)
