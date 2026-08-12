"""Auditoria LLM em lote — parser e loteamento (steps/auditor.py).

Fixa a correção medida em 2026-08-11: `run_content_audit` e `run_title_verify`
chamavam o LLM UMA VEZ POR LIVRO. Com AUDIT_LLM_POR_CICLO=25 isso consumiu 25
chamadas num único slot (claude_usage_tracker: calls_today 5 -> 30), contra uma
janela da sessão PRO que comporta 5-6 chamadas.

O que este teste protege é o INVARIANTE DE CUSTO: N livros custam
ceil(N / AUDIT_BATCH_SIZE) chamadas, não N.

Convenção do projeto: assert puro, sem pytest. `auditor` importa requests,
bs4 e dotenv — stubados em sys.modules antes do import, e só quando o real está
ausente (mesma técnica de tests/test_backfill_idioma.py).
"""

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub(nome, **attrs):
    try:
        __import__(nome)
        return
    except ImportError:
        pass
    mod = types.ModuleType(nome)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nome] = mod


def _boom(*a, **k):
    raise AssertionError("saída de rede não esperada no teste")


_stub("requests", get=_boom, post=_boom, head=_boom,
      exceptions=types.SimpleNamespace(ConnectionError=Exception,
                                       RequestException=Exception,
                                       Timeout=Exception))
_stub("bs4", BeautifulSoup=lambda *a, **k: None)
_stub("dotenv", load_dotenv=lambda *a, **k: None)

from steps import auditor  # noqa: E402


# ── 1. Parser: array limpo ──────────────────────────────────────────────────
raw = json.dumps([
    {"slug": "a", "severity": "none", "issues": [], "summary": "ok"},
    {"slug": "b", "severity": "high", "issues": ["x"], "summary": "ruim"},
])
r = auditor._parse_llm_audit_batch(raw)
assert set(r) == {"a", "b"}, r
assert r["b"]["severity"] == "high"

# ── 2. Parser: cercado em markdown ──────────────────────────────────────────
r = auditor._parse_llm_audit_batch("```json\n" + raw + "\n```")
assert set(r) == {"a", "b"}, r

# ── 3. Parser: texto solto em volta do array ────────────────────────────────
# O modelo às vezes explica antes de responder; o recorte pelo par externo de
# colchetes tem de sobreviver a isso.
r = auditor._parse_llm_audit_batch("Segue a análise:\n" + raw + "\nEspero ter ajudado.")
assert set(r) == {"a", "b"}, r

# ── 4. Parser: lixo devolve vazio, não explode ──────────────────────────────
assert auditor._parse_llm_audit_batch("desculpe, não consegui") == {}
assert auditor._parse_llm_audit_batch("") == {}
assert auditor._parse_llm_audit_batch(None) == {}
assert auditor._parse_llm_audit_batch('{"slug": "a"}') == {}, "objeto solto não é array"

# ── 5. Parser: item sem slug é descartado ───────────────────────────────────
# Sem slug não dá para saber de quem é o veredito — gravar seria atribuir a
# auditoria ao livro errado.
r = auditor._parse_llm_audit_batch(json.dumps([
    {"severity": "high", "issues": ["sem slug"]},
    {"slug": "c", "severity": "none"},
]))
assert set(r) == {"c"}, r


# ── 6. INVARIANTE DE CUSTO: N livros -> ceil(N/BATCH) chamadas ──────────────
class _Contador:
    def __init__(self, resposta_por_lote=True):
        self.chamadas = 0
        self.tamanhos = []
        self.resposta_por_lote = resposta_por_lote

    def __call__(self, prompt, timeout=None, **kw):
        self.chamadas += 1
        n = prompt.count("--- LIVRO ")
        self.tamanhos.append(n)
        if not self.resposta_por_lote:
            return False, "erro simulado"
        slugs = [l.split("SLUG: ")[1].split("\n")[0]
                 for l in prompt.split("--- LIVRO ")[1:]]
        return True, json.dumps([
            {"slug": s, "real": True, "confidence": "high", "reason": "ok",
             "severity": "none", "issues": [], "summary": "ok"} for s in slugs
        ])


orig_run_prompt = auditor.run_prompt
orig_batch_size = auditor.AUDIT_BATCH_SIZE
try:
    auditor.AUDIT_BATCH_SIZE = 10
    for n_livros, esperado in [(1, 1), (10, 1), (11, 2), (25, 3), (30, 3)]:
        c = _Contador()
        auditor.run_prompt = c
        itens = [(f"slug{i}", f"Titulo {i}", "Autor", "desc")
                 for i in range(n_livros)]
        res = auditor._verify_titles_batch(itens)
        assert c.chamadas == esperado, (
            f"{n_livros} livros deviam custar {esperado} chamada(s), "
            f"custaram {c.chamadas}"
        )
        assert len(res) == n_livros, f"{n_livros} livros, {len(res)} vereditos"
        assert sum(c.tamanhos) == n_livros, c.tamanhos

    # O caso que motivou tudo: 25 livros custavam 25 chamadas.
    c = _Contador()
    auditor.run_prompt = c
    auditor._verify_titles_batch([(f"s{i}", f"T{i}", "A", "d") for i in range(25)])
    assert c.chamadas == 3, c.chamadas
    assert c.chamadas < 25

    # ── 7. Lote que falha não inventa veredito ──────────────────────────────
    c = _Contador(resposta_por_lote=False)
    auditor.run_prompt = c
    res = auditor._verify_titles_batch([(f"s{i}", f"T{i}", "A", "d") for i in range(5)])
    assert res == {}, f"lote falho não pode produzir veredito: {res}"

    # ── 8. Timeout escala com o tamanho do lote ─────────────────────────────
    capturado = {}

    def _captura(prompt, timeout=None, **kw):
        capturado["timeout"] = timeout
        return True, "[]"

    auditor.run_prompt = _captura
    auditor._verify_titles_batch([(f"s{i}", f"T{i}", "A", "d") for i in range(10)])
    esperado_t = (auditor.AUDIT_BATCH_TIMEOUT_BASE
                  + auditor.AUDIT_BATCH_TIMEOUT_POR_LIVRO * 10)
    assert capturado["timeout"] == esperado_t, capturado
    assert capturado["timeout"] > 120, "lote de 10 precisa de mais que os 120s antigos"
finally:
    auditor.run_prompt = orig_run_prompt
    auditor.AUDIT_BATCH_SIZE = orig_batch_size

print("test_auditor_batch OK")
