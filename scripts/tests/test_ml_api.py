"""API de catalogo do ML: o portao do autor e o contrato do pre-voo.

Fixa TASK-OFERTAS-005. O caso central e o falso positivo MEDIDO em 2026-08-29:
a /products/search do ML NUNCA responde "nao achei" — devolve o mais parecido.
Numa amostra de 70 livros publicados, 97% "encontraram" produto e 19 desses
eram livro ERRADO.

    PYTHONPATH=. python tests/test_ml_api.py
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core import ml_api  # noqa: E402  (stdlib only: urllib, json, re)


# ── 1. O falso positivo medido nao pode passar ──────────────────────────────
# "Sob a Roda" (Hermann Hesse) -> a API devolveu "Sob a Selva", de
# Cornaccioni/Ichigo. Sem o portao do autor, isso viraria preco e DEEP LINK do
# livro errado — pior que o scraping que veio substituir.
assert ml_api._autor_confere("Hermann Hesse", "Cornaccioni, Gustavo/Ichigo, Andy") is False
assert ml_api._autor_confere("Agatha Christie", "Ana Laura") is False
assert ml_api._autor_confere("Michelle McNamara", "Teren Mikami") is False
assert ml_api._autor_confere("Sérgio Vaz", "Sofia Sampaio") is False
print("[OK] os 4 falsos positivos medidos sao rejeitados")

# ── 2. As duas grafias que o ML usa para o mesmo autor casam ────────────────
assert ml_api._autor_confere("Machado de Assis", "Machado de Assis") is True
assert ml_api._autor_confere("Douglas Adams", "Adams, Douglas") is True
assert ml_api._autor_confere("Napoleon Hill", "Hill, Napoleon") is True
assert ml_api._autor_confere("Marshall Rosenberg", "Rosenberg, Marshall") is True
print("[OK] 'Nome Sobrenome' e 'Sobrenome, Nome' casam")

# ── 3. Acento e caixa nao atrapalham ────────────────────────────────────────
assert ml_api._autor_confere("José Saramago", "SARAMAGO, Jose") is True
print("[OK] acento e caixa normalizados")

# ── 4. Indeterminado NAO e aprovacao ────────────────────────────────────────
# Quando falta um dos lados nao da para afirmar nada. `buscar_livro` trata
# `None` como reprovacao — falso negativo custa um item sem preco (o estado de
# hoje); falso positivo publica produto errado.
assert ml_api._autor_confere(None, "Machado de Assis") is None
assert ml_api._autor_confere("Machado de Assis", None) is None
assert ml_api._autor_confere("", "") is None
print("[OK] indeterminado devolve None (e buscar_livro rejeita)")

# ── 5. Tokens curtos nao criam casamento acidental ──────────────────────────
# "de", "da", "e" apareceriam em quase todo nome brasileiro.
assert ml_api._autor_confere("Ana de Souza", "Carlos de Oliveira") is False
print("[OK] preposicoes nao casam autores diferentes")

# ── 6. Pre-voo sem credencial nao explode e nao vaza ────────────────────────
_id, _sec = os.environ.pop("ML_CLIENT_ID", None), os.environ.pop("ML_CLIENT_SECRET", None)
try:
    assert ml_api.configurado() is False
    estado, detalhe = ml_api.status()
    assert estado == "sem_credencial", (estado, detalhe)
    assert "ML_CLIENT_ID" in detalhe
finally:
    if _id:
        os.environ["ML_CLIENT_ID"] = _id
    if _sec:
        os.environ["ML_CLIENT_SECRET"] = _sec
print("[OK] status() sem credencial devolve 'sem_credencial', sem exceção")

# ── 7. O contrato do pre-voo e o mesmo do claude_runner.session_status() ────
# O G decide o que fazer com base nesses estados; mudar o vocabulario aqui
# quebraria o main.py em silencio.
assert set(("ok", "sem_credencial", "auth", "erro")) >= {"ok", "sem_credencial"}
import inspect  # noqa: E402
fonte = inspect.getsource(ml_api.status)
for estado in ("ok", "sem_credencial", "auth", "erro"):
    assert f'"{estado}"' in fonte, f"status() nao pode deixar de devolver {estado}"
print("[OK] status() mantem os 4 estados do contrato do pre-voo")

# ── 8. buscar_livro sem token devolve None, nao levanta ─────────────────────
_orig = ml_api.token
ml_api.token = lambda forcar=False: None
try:
    assert ml_api.buscar_livro("Dom Casmurro", "Machado de Assis") is None
finally:
    ml_api.token = _orig
print("[OK] buscar_livro sem token devolve None")

# ── 9. A URL do produto e a forma canonica confirmada em navegador ──────────
assert ml_api.URL_PRODUTO.format(produto_id="MLB20090573") == \
    "https://www.mercadolivre.com.br/p/MLB20090573"
print("[OK] URL_PRODUTO monta a forma canonica /p/<catalog_product_id>")

# ── 10-14. Erro da API NAO e "nao achou" (bug corrigido em 2026-09-16) ──────
# `_produtos`/`_preco` engoliam qualquer excecao e `buscar_livro` devolvia None,
# o mesmo valor de "avaliou e nao confirmou". O step 31 carimbava o livro como
# avaliado. Estes casos exercitam o MODULO REAL, com urlopen trocado — nao um
# stub do contrato, que foi justamente o que deixou o bug passar: o teste do
# step 31 simulava uma excecao que o ml_api de verdade nunca levantava.
import io as _io  # noqa: E402
import urllib.error as _uerr  # noqa: E402

_orig_urlopen = ml_api.urllib.request.urlopen
_orig_sleep = ml_api.time.sleep
_dormiu = []
ml_api.time.sleep = lambda s: _dormiu.append(s)


def _http(code):
    def _abrir(req, timeout=None):
        raise _uerr.HTTPError(req.full_url, code, "x", {}, _io.BytesIO(b"{}"))
    return _abrir


try:
    # 10. 429 persistente: espera escalonada e LimiteML, nunca None
    _dormiu.clear()
    ml_api.urllib.request.urlopen = _http(429)
    try:
        ml_api._get("https://api.mercadolibre.com/x", "tk")
        raise AssertionError("429 persistente deveria levantar LimiteML")
    except ml_api.LimiteML:
        pass
    esperas = [s for s in _dormiu if s >= 10]
    assert esperas == list(ml_api.ESPERAS_429), esperas
    print("[OK] 429 persistente espera 10/30/60 s e levanta LimiteML")

    # 11. buscar_livro PROPAGA o limite — nao devolve None
    _orig_tk = ml_api.token
    ml_api.token = lambda forcar=False: "tk"
    try:
        ml_api.buscar_livro("Dom Casmurro", "Machado de Assis")
        raise AssertionError("buscar_livro engoliu o limite")
    except ml_api.ErroAPIML:
        pass
    print("[OK] buscar_livro levanta ErroAPIML em vez de devolver None")

    # 12. 5xx tambem e "nao avaliou"
    ml_api.urllib.request.urlopen = _http(503)
    try:
        ml_api._produtos("dom casmurro", "tk")
        raise AssertionError("503 deveria virar ErroAPIML")
    except ml_api.ErroAPIML:
        pass
    print("[OK] 5xx vira ErroAPIML")

    # 13. 4xx deterministico e "nao achou" — senao vira laco de fila sem carimbo
    ml_api.urllib.request.urlopen = _http(400)
    assert ml_api._produtos("consulta estranha", "tk") == []
    ml_api.urllib.request.urlopen = _http(404)
    assert ml_api._preco("MLB0", "tk") == (None, None)
    assert ml_api.buscar_livro("Titulo", "Autor") is None
    ml_api.token = _orig_tk
    print("[OK] 400/404 sao 'nao achou' (determinsticos), nao erro de avaliacao")

    # 14. ritmo minimo entre chamadas
    _dormiu.clear()
    ml_api._ultima_chamada["t"] = ml_api.time.monotonic()
    ml_api._ritmo()
    assert _dormiu and 0 < _dormiu[0] <= ml_api.INTERVALO_MIN, _dormiu
    print(f"[OK] _ritmo espera ate {ml_api.INTERVALO_MIN}s entre chamadas")
finally:
    ml_api.urllib.request.urlopen = _orig_urlopen
    ml_api.time.sleep = _orig_sleep

print("\nTodos os testes passaram.")
