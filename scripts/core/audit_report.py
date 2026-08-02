"""
core/audit_report.py — Escritor unificado de relatórios de auditoria.

Fonte única de verdade do formato/numeração dos relatórios de auditoria do site.
Todos os produtores (auditor.py, autopilot_audit, consistency_check,
offer_price_monitor, …) emitem o MESMO arquivo:

    scripts/data/logs/NNNN_audit_<mode>.json

consumido pelo comando /audit (agents/audit_batch/prompt.md), que lê, corrige e
arquiva em scripts/data/log_analysis/processed_logs/.

Unificar a saída (WS — "P1") faz o /audit cobrir o site inteiro com um único
consumidor, em vez de 5 formatos dispersos (logs soltos, audit_log,
connectivity_log, offer_price_log, batch/*_consistency.json).
"""

from pathlib import Path
from datetime import datetime, timezone
import json

# scripts/data/logs — relativo a este arquivo (scripts/core/audit_report.py)
REPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "logs"


def _next_sequence(log_dir: Path) -> int:
    """Próximo NNNN (4 dígitos), varrendo logs/ E log_analysis/processed_logs/.

    Incluir processed_logs/ evita reutilizar NNNNs de relatórios já arquivados:
    quando todos os relatórios foram processados, logs/ fica vazia e sem este
    check o próximo começaria em 0001, sobrescrevendo o homônimo já arquivado.
    """
    # log_dir = scripts/data/logs → processed = scripts/data/log_analysis/processed_logs
    processed_dir = log_dir.parent / "log_analysis" / "processed_logs"
    all_files = list(log_dir.glob("[0-9][0-9][0-9][0-9]_*.json"))
    if processed_dir.exists():
        all_files += list(processed_dir.glob("[0-9][0-9][0-9][0-9]_*.json"))
    if not all_files:
        return 1
    return max(int(f.name[:4]) for f in all_files) + 1


# Campos que mudam a cada gravação e NÃO distinguem um relatório de outro —
# ignorados ao comparar conteúdo para deduplicar.
_VOLATILE_KEYS = ("generated_at", "timestamp")


def _payload_fingerprint(data: dict) -> str:
    corpo = {k: v for k, v in data.items() if k not in _VOLATILE_KEYS}
    return json.dumps(corpo, sort_keys=True, ensure_ascii=False, default=str)


def _pending_latest(log_dir: Path, mode: str) -> Path | None:
    """Relatório mais recente deste modo AINDA na fila (logs/), ou None.

    Compara só contra a fila pendente, de propósito: se o homônimo já foi
    arquivado, `logs/` não representa mais o estado atual e o relatório novo
    precisa ser escrito, mesmo idêntico.
    """
    candidatos = list(log_dir.glob(f"[0-9][0-9][0-9][0-9]_audit_{mode}.json"))
    if not candidatos:
        return None
    return max(candidatos, key=lambda f: int(f.name[:4]))


def save_audit_report(data: dict, mode: str | None = None,
                      dedupe: bool = True) -> str:
    """Grava um relatório de auditoria padronizado e retorna o caminho (str).

    - `mode`: usado no nome do arquivo. Se omitido, usa `data["mode"]`.
    - Acrescenta `mode` e `generated_at` ao payload se ausentes (não sobrescreve).
    - Nome: `NNNN_audit_<mode>.json`, com NNNN sequencial por diretório.
    - `dedupe`: se o relatório mais recente do mesmo modo AINDA na fila tem
      conteúdo idêntico (ignorando `_VOLATILE_KEYS`), não grava nada e devolve o
      caminho do existente.

    Por que deduplicar: `autopilot_audit.run()` grava um relatório de integridade
    a cada saída do autopilot, e o autopilot é reinvocado várias vezes por passe
    do G. Medido em 2026-08-01 nos arquivos de 2026-07-30 (15:37→19:24):
    **16 relatórios de integridade, apenas 6 com conteúdo distinto — 11
    byte-idênticos** ignorando o timestamp, incluindo o primeiro e o último.
    Relatório repetido não informa nada e ainda empurra a numeração NNNN.
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    mode = mode or data.get("mode", "audit")
    data.setdefault("mode", mode)
    data.setdefault("generated_at", datetime.now(timezone.utc).isoformat())

    if dedupe:
        anterior = _pending_latest(REPORT_DIR, mode)
        if anterior is not None:
            try:
                previo = json.loads(anterior.read_text(encoding="utf-8"))
                if _payload_fingerprint(previo) == _payload_fingerprint(data):
                    return str(anterior)
            except Exception:
                pass  # ilegível/corrompido: grava o novo normalmente

    seq = _next_sequence(REPORT_DIR)
    path = REPORT_DIR / f"{seq:04d}_audit_{mode}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(path)
