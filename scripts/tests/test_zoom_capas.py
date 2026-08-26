"""Normalizacao do zoom das capas do Google Books (assert puro, sem pytest).

Fixa a correcao de 2026-08-26: `covers.fetch_google_cover` fazia
replace("&zoom=1", "&zoom=0") com o comentario "remove zoom baixo", e zoom=0 e
a resolucao CHEIA. Medido no books.db: 1.294 das 2.137 capas do Google Books
(60%) ficaram em zoom=0, servindo centenas de KB para um slot de 176x256 px que
ainda por cima tem `priority` (elemento de LCP).

    PYTHONPATH=. python tests/test_zoom_capas.py
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# covers.py importa requests e dotenv no topo, e o CI nao roda pip install.
# Stub so quando o real esta ausente (mesma tecnica de test_backfill_idioma).
for _nome, _attrs in (
    ("requests", {"get": lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("requests.get foi chamado — este teste nao faz rede"))}),
    ("dotenv", {"load_dotenv": lambda *a, **k: None}),
):
    try:
        __import__(_nome)
    except ModuleNotFoundError:  # pragma: no cover — so no CI
        _m = types.ModuleType(_nome)
        for _k, _v in _attrs.items():
            setattr(_m, _k, _v)
        sys.modules[_nome] = _m

from steps.covers import ZOOM_GOOGLE_BOOKS, normalizar_capa_google  # noqa: E402

GB = "https://books.google.com/books/content?id=X&printsec=frontcover&img=1"


# ── 1. O caso que causou o passivo: zoom=0 vira o alvo ──────────────────────
assert normalizar_capa_google(f"{GB}&zoom=0") == f"{GB}&zoom={ZOOM_GOOGLE_BOOKS}"
print("[OK] zoom=0 (resolucao cheia) e reescrito para o alvo")

# ── 2. Qualquer outro zoom tambem converge para o alvo ──────────────────────
for z in ("1", "3", "5"):
    assert normalizar_capa_google(f"{GB}&zoom={z}") == f"{GB}&zoom={ZOOM_GOOGLE_BOOKS}"
print("[OK] qualquer zoom converge para o alvo")

# ── 3. Sem zoom na URL, o parametro e acrescentado ──────────────────────────
assert normalizar_capa_google(GB) == f"{GB}&zoom={ZOOM_GOOGLE_BOOKS}"
# e com '?' ausente, usa '?' em vez de '&'
assert normalizar_capa_google("https://books.google.com/x") == \
    f"https://books.google.com/x?zoom={ZOOM_GOOGLE_BOOKS}"
print("[OK] acrescenta zoom quando nao havia, com o separador certo")

# ── 4. Idempotente — e o que torna o backfill re-executavel ─────────────────
uma = normalizar_capa_google(f"{GB}&zoom=0")
assert normalizar_capa_google(uma) == uma
print("[OK] idempotente")

# ── 5. NAO toca em outros hosts ─────────────────────────────────────────────
# O OpenLibrary usa sufixo -L/-M no path; mexer nele aqui quebraria 2.472 capas.
ol = "https://covers.openlibrary.org/b/id/12986869-L.jpg"
assert normalizar_capa_google(ol) == ol
amz = "https://images-na.ssl-images-amazon.com/images/P/8535914846.jpg"
assert normalizar_capa_google(amz) == amz
print("[OK] OpenLibrary e Amazon passam intactas")

# ── 6. None / vazio nao explodem ────────────────────────────────────────────
assert normalizar_capa_google(None) is None
assert normalizar_capa_google("") == ""
print("[OK] None e string vazia sao devolvidos como vieram")

# ── 7. O alvo nao pode voltar a ser 0 sem alguem ver este teste ─────────────
assert ZOOM_GOOGLE_BOOKS != "0", (
    "zoom=0 e resolucao cheia — foi exatamente o que causou as 1.294 capas "
    "pesadas medidas em 2026-08-26")
print("[OK] o alvo nao e zoom=0")

# ── 8. http:// vira https:// no mesmo passe ─────────────────────────────────
# Medido em 2026-08-26: 837 capas PUBLICADAS estavam em http:// numa pagina
# HTTPS — conteudo misto. E o mesmo campo e o mesmo passe do zoom, entao a
# normalizacao trata os dois.
http_gb = ("http://books.google.com/books/content?id=X&printsec=frontcover"
           "&img=1&zoom=1&edge=curl")
saida = normalizar_capa_google(http_gb)
assert saida.startswith("https://"), saida
assert f"zoom={ZOOM_GOOGLE_BOOKS}" in saida, saida
assert "http://" not in saida, saida
print("[OK] http:// do Google Books e promovido a https:// junto com o zoom")

# Uma capa ja canonica (https + zoom alvo) nao pode ser reescrita — senao o
# backfill reenviaria o catalogo inteiro ao Supabase a cada execucao.
canonica = f"{GB}&zoom={ZOOM_GOOGLE_BOOKS}"
assert normalizar_capa_google(canonica) == canonica
print("[OK] capa ja canonica passa intacta (backfill nao reenvia)")

print("\nTodos os testes passaram.")
