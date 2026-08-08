"""
Tolerancia do loader de seeds de jogos (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_jogos_load_seeds.py

Contexto: ate 2026-07-28 `jogos_pipeline._load_seeds` nao removia cerca de
markdown nem tolerava BOM, enquanto o prompt do seeder de jogos mandava
entregar "dentro de bloco de codigo". O arquivo cercado nao quebrava o
pipeline (import_seeds captura a excecao), mas era logado como ERRO e ficava
parado em seeds/ para sempre. O infantil ja tolerava as duas coisas.
"""

import json
import os
import sys
import tempfile
import types

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)


# jogos_pipeline importa requests no topo e o CI nao roda pip install. O loader
# nao toca em rede, entao basta o nome existir. Stub so quando o real esta
# ausente, para que localmente o import de verdade continue sendo exercitado.
def _stub_requests():
    m = types.ModuleType("requests")

    def _boom(*_a, **_k):
        raise AssertionError("teste nao deve fazer requisicao HTTP")

    m.get = _boom
    m.post = _boom
    m.Session = lambda *a, **k: _boom()
    m.utils = types.SimpleNamespace(quote=lambda s, safe="/": s)
    m.exceptions = types.SimpleNamespace(
        ReadTimeout=type("ReadTimeout", (Exception,), {}),
        RequestException=type("RequestException", (Exception,), {}),
    )
    sys.modules["requests"] = m


try:
    import requests  # noqa: F401
except ImportError:
    _stub_requests()

from steps.jogos_pipeline import _load_seeds  # noqa: E402

ITENS = [
    {
        "titulo": "Catan",
        "autor": "Klaus Teuber",
        "marketplace": "amazon",
        "lookup_query": "Catan jogo de tabuleiro",
        "categoria": "Jogos de Tabuleiro",
        "idioma": "PT",
        "ano_lancamento": 1995,
    },
    {
        "titulo": "Tormenta20",
        "autor": "Leonel Caldela",
        "marketplace": "mercado_livre",
        "lookup_query": "Tormenta20 RPG",
        "categoria": "RPG",
        "idioma": "PT",
        "ano_lancamento": 2020,
    },
]


def _escrever(texto, encoding="utf-8"):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write(texto)
    return path


def _checar(path, rotulo):
    try:
        seeds = _load_seeds(path)
        assert seeds == ITENS, f"{rotulo}: conteudo divergente -> {seeds!r}"
        print(f"  OK  {rotulo}")
    finally:
        os.unlink(path)


def main():
    puro = json.dumps(ITENS, ensure_ascii=False, indent=2)

    print("teste: _load_seeds de jogos tolera as tres deformacoes conhecidas")

    _checar(_escrever(puro), "JSON puro (caso normal)")
    _checar(_escrever("\n" + puro + "\n\n"), "JSON com espaco em volta")
    _checar(_escrever("```json\n" + puro + "\n```"), "cerca de markdown ```json")
    _checar(_escrever("```\n" + puro + "\n```"), "cerca de markdown sem linguagem")
    _checar(_escrever(puro, encoding="utf-8-sig"), "BOM UTF-8")
    _checar(_escrever("```json\n" + puro + "\n```", encoding="utf-8-sig"), "BOM + cerca")
    _checar(
        _escrever("\n".join(json.dumps(i, ensure_ascii=False) for i in ITENS)),
        "JSONL (um objeto por linha)",
    )

    print("\nOK: 7 formatos aceitos")


if __name__ == "__main__":
    main()
