# ============================================================
# BATCH NUMBERING
# Livraria Alexandria
#
# Utilitário para calcular o próximo número de lote disponível
# para os arquivos de batch (synopsis e categorize).
# ============================================================

import glob
import os
import re

NUM_PAT = re.compile(r"^(\d{3})_")


def pending_batch_input(data_dir: str, prefix: str) -> str | None:
    """Menor-numerado `NNN_{prefix}_input.json` ainda SEM output correspondente.

    Replica exatamente a regra que os prompts dos agentes batch executam à mão
    com Glob/Read (seção "Input": selecionar o de menor número; pular os que já
    têm `NNN_{prefix}_output.json` porque o `mv` falhou num ciclo anterior).

    Resolver isso em Python economiza os turnos de descoberta do agente **sem
    mudar a semântica** — em particular, continua drenando lotes órfãos de
    ciclos anteriores ANTES do lote recém-exportado. Por isso a resolução é
    feita aqui e não passando o path do export: o export não sabe de órfãos.

    Retorna None quando não há lote pendente (o agente então segue o fluxo
    normal do prompt e reporta "nenhum input pendente").
    """
    inputs = glob.glob(os.path.join(data_dir, f"*_{prefix}_input.json"))

    candidatos = []
    for path in inputs:
        m = NUM_PAT.match(os.path.basename(path))
        if not m:
            continue
        num = m.group(1)
        output = os.path.join(data_dir, f"{num}_{prefix}_output.json")
        if os.path.exists(output):
            continue  # já processado — mv falhou, mas o trabalho foi feito
        candidatos.append((num, path))

    if not candidatos:
        return None

    return min(candidatos)[1]


def next_batch_number(data_dir: str, prefix: str) -> str:
    """
    Retorna o próximo número zero-padded (ex: '003') para o prefixo dado.

    prefix: 'synopsis' ou 'categorize'

    Varre data_dir/ e data_dir/processed_{prefix}/ para encontrar o
    maior número já usado e retorna max + 1.
    Varrer as duas pastas é crítico para evitar reutilizar números de
    lotes já arquivados.
    """
    processed_dir  = os.path.join(data_dir, f"processed_{prefix}")
    reclaimed_dir  = os.path.join(processed_dir, "reclaimed")
    patterns = [
        os.path.join(data_dir,      f"*_{prefix}_input.json"),
        os.path.join(data_dir,      f"*_{prefix}_output.json"),
        os.path.join(processed_dir, f"*_{prefix}_input.json"),
        os.path.join(processed_dir, f"*_{prefix}_output.json"),
        # Lotes arquivados pelo reclaim ficam em reclaimed/ para não
        # interferir na detecção de lotes em voo — mas os números devem
        # ser respeitados para evitar reutilização de NNNs.
        os.path.join(reclaimed_dir, f"*_{prefix}_input.json"),
        os.path.join(reclaimed_dir, f"*_{prefix}_output.json"),
    ]
    max_num = 0
    for pattern in patterns:
        for path in glob.glob(pattern):
            m = NUM_PAT.match(os.path.basename(path))
            if m:
                max_num = max(max_num, int(m.group(1)))
    return f"{max_num + 1:03d}"
