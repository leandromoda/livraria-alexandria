"""core/audit_report.py — dedupe de relatórios idênticos e numeração NNNN.

Motivado pela análise de 2026-08-01: autopilot_audit grava um relatório de
integridade a cada saída do autopilot, e o autopilot é reinvocado várias vezes
por passe do G. Nos arquivos de 2026-07-30 (15:37→19:24) havia 16 relatórios de
integridade com apenas 6 conteúdos distintos — 11 byte-idênticos.

Só stdlib. REPORT_DIR é reapontado por monkeypatch para um diretório temporário,
então o teste não toca em scripts/data/logs/.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import audit_report


def _com_dir_temporario(fn):
    """Roda fn(logs) com REPORT_DIR apontando para um diretório novo.

    A árvore é <tmp>/data/logs, e não <tmp> direto, porque `_next_sequence`
    também varre `REPORT_DIR.parent/log_analysis/processed_logs`. Com REPORT_DIR
    na raiz do TemporaryDirectory, esse irmão cairia no temp do SISTEMA — vazando
    entre execuções e tornando o teste dependente de histórico (foi o que
    aconteceu: passou isolado e quebrou na suíte, com a numeração em 0002).
    """
    original = audit_report.REPORT_DIR
    with tempfile.TemporaryDirectory() as d:
        logs = Path(d) / "data" / "logs"
        logs.mkdir(parents=True)
        audit_report.REPORT_DIR = logs
        try:
            fn(logs)
        finally:
            audit_report.REPORT_DIR = original


# ── 1. Relatório idêntico não gera arquivo novo ─────────────────────────────
def caso_dedupe(tmp):
    payload = {"mode": "integrity", "total_checks": 9, "results": [{"count": 0}]}

    p1 = audit_report.save_audit_report(dict(payload))
    p2 = audit_report.save_audit_report(dict(payload))
    p3 = audit_report.save_audit_report(dict(payload))

    arquivos = sorted(tmp.glob("*_audit_integrity.json"))
    assert len(arquivos) == 1, f"esperava 1 arquivo, veio {[f.name for f in arquivos]}"
    assert p1 == p2 == p3, f"caminhos divergiram: {p1} {p2} {p3}"
    assert arquivos[0].name == "0001_audit_integrity.json", arquivos[0].name


_com_dir_temporario(caso_dedupe)


# ── 2. Conteúdo diferente gera arquivo novo, com NNNN seguinte ──────────────
def caso_conteudo_novo(tmp):
    audit_report.save_audit_report({"mode": "integrity", "total_checks": 9})
    audit_report.save_audit_report({"mode": "integrity", "total_checks": 10})

    arquivos = sorted(f.name for f in tmp.glob("*_audit_integrity.json"))
    assert arquivos == ["0001_audit_integrity.json", "0002_audit_integrity.json"], arquivos


_com_dir_temporario(caso_conteudo_novo)


# ── 3. generated_at diferente NÃO conta como conteúdo novo ──────────────────
def caso_timestamp_volatil(tmp):
    audit_report.save_audit_report(
        {"mode": "prices", "total": 3, "generated_at": "2026-07-30T10:00:00+00:00"})
    audit_report.save_audit_report(
        {"mode": "prices", "total": 3, "generated_at": "2026-07-30T19:00:00+00:00"})

    arquivos = list(tmp.glob("*_audit_prices.json"))
    assert len(arquivos) == 1, f"timestamp furou o dedupe: {[f.name for f in arquivos]}"


_com_dir_temporario(caso_timestamp_volatil)


# ── 4. Modos diferentes não interferem entre si ─────────────────────────────
def caso_modos_independentes(tmp):
    audit_report.save_audit_report({"mode": "integrity", "x": 1})
    audit_report.save_audit_report({"mode": "connectivity", "x": 1})

    assert len(list(tmp.glob("*_audit_integrity.json"))) == 1
    assert len(list(tmp.glob("*_audit_connectivity.json"))) == 1


_com_dir_temporario(caso_modos_independentes)


# ── 5. Se o homônimo já foi ARQUIVADO, grava de novo ────────────────────────
# A fila (logs/) precisa refletir o estado atual; comparar contra processed_logs/
# deixaria o /audit sem relatório nenhum para revisar.
def caso_arquivado_nao_bloqueia(tmp):
    payload = {"mode": "integrity", "total_checks": 9}
    p1 = Path(audit_report.save_audit_report(dict(payload)))

    processed = tmp.parent / "log_analysis" / "processed_logs"
    processed.mkdir(parents=True, exist_ok=True)
    p1.rename(processed / p1.name)               # simula a poda

    audit_report.save_audit_report(dict(payload))

    pendentes = list(tmp.glob("*_audit_integrity.json"))
    assert len(pendentes) == 1, f"nao regravou apos arquivar: {pendentes}"
    # NNNN não pode colidir com o arquivado (0001)
    assert pendentes[0].name == "0002_audit_integrity.json", pendentes[0].name


_com_dir_temporario(caso_arquivado_nao_bloqueia)


# ── 6. dedupe=False força a gravação ────────────────────────────────────────
def caso_opt_out(tmp):
    payload = {"mode": "integrity", "x": 1}
    audit_report.save_audit_report(dict(payload))
    audit_report.save_audit_report(dict(payload), dedupe=False)

    assert len(list(tmp.glob("*_audit_integrity.json"))) == 2


_com_dir_temporario(caso_opt_out)


# ── 7. O arquivo gravado continua sendo JSON válido com mode/generated_at ───
def caso_formato(tmp):
    p = Path(audit_report.save_audit_report({"total_checks": 9}, mode="integrity"))
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["mode"] == "integrity", d
    assert "generated_at" in d, d


_com_dir_temporario(caso_formato)

print("test_audit_report_dedupe OK")
