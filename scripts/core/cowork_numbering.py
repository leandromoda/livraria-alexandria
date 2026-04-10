# ============================================================
# COWORK NUMBERING
# Livraria Alexandria
#
# Utilitário para calcular o próximo número de lote disponível
# para os arquivos de cowork (synopsis e classify).
# ============================================================

import glob
import os
import re

NUM_PAT = re.compile(r"^(\d{3})_")


def next_batch_number(data_dir: str, prefix: str) -> str:
    """
    Retorna o próximo número zero-padded (ex: '003') para o prefixo dado.

    prefix: 'synopsis' ou 'classify'

    Varre data_dir/ e data_dir/processed_{prefix}/ para encontrar o
    maior número já usado e retorna max + 1.
    Varrer as duas pastas é crítico para evitar reutilizar números de
    lotes já arquivados.
    """
    processed_dir = os.path.join(data_dir, f"processed_{prefix}")
    patterns = [
        os.path.join(data_dir,      f"*_{prefix}_input.json"),
        os.path.join(data_dir,      f"*_{prefix}_output.json"),
        os.path.join(processed_dir, f"*_{prefix}_input.json"),
        os.path.join(processed_dir, f"*_{prefix}_output.json"),
    ]
    max_num = 0
    for pattern in patterns:
        for path in glob.glob(pattern):
            m = NUM_PAT.match(os.path.basename(path))
            if m:
                max_num = max(max_num, int(m.group(1)))
    return f"{max_num + 1:03d}"
