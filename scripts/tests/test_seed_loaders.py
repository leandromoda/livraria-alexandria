"""
Tolerancia dos TRES loaders de seed (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_seed_loaders.py

Contexto (2026-07-28): os tres pipelines paralelos liam seed de tres jeitos
diferentes, e dois dos tres loaders NAO aceitavam o formato que o proprio
prompt do seeder mandava produzir:

    pipeline   loader                        BOM  cerca  prompt pedia
    livros     offer_seed.load_seeds         nao  nao    bloco de codigo
    jogos      jogos_pipeline._load_seeds    nao  nao    bloco de codigo
    infantis   infantis_pipeline._load_seeds sim  sim    JSON puro

Um seed cercado nao quebrava o pipeline (import_seeds captura a excecao), mas
era logado como ERRO e ficava parado em seeds/ para sempre — falha silenciosa.
Os tres prompts passaram a exigir JSON puro e os tres loaders passaram a
tolerar as tres deformacoes. Este teste fixa a paridade: o que um aceita,
todos aceitam.
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

from steps.infantis_pipeline import _load_seeds as load_infantis  # noqa: E402
from steps.jogos_pipeline import _load_seeds as load_jogos  # noqa: E402
from steps.offer_seed import load_seeds as load_livros  # noqa: E402

LOADERS = [
    ("livros   (offer_seed.load_seeds)", load_livros),
    ("jogos    (jogos_pipeline)", load_jogos),
    ("infantis (infantis_pipeline)", load_infantis),
]

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
    """Roda o MESMO arquivo nos tres loaders — paridade e o que se testa."""
    try:
        for nome, loader in LOADERS:
            seeds = loader(path)
            assert seeds == ITENS, f"{rotulo} / {nome}: divergente -> {seeds!r}"
        print(f"  OK  {rotulo}")
    finally:
        os.unlink(path)


def main():
    puro = json.dumps(ITENS, ensure_ascii=False, indent=2)

    print("teste: os 3 loaders de seed toleram as mesmas deformacoes")

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

    print(f"\nOK: 7 formatos x {len(LOADERS)} loaders = {7 * len(LOADERS)} combinacoes")


if __name__ == "__main__":
    main()
