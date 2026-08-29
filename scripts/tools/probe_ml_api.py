# ============================================================
# SONDA — API do Mercado Livre
# Livraria Alexandria
#
# Responde TRES perguntas antes de escrever qualquer cliente:
#   1. O grant client_credentials funciona com as chaves do app?
#   2. O token de aplicacao e aceito na busca de produtos?
#   3. A resposta traz o que precisamos — preco e URL de produto?
#
# Nao escreve nada no banco. Nao imprime o secret.
#
# Uso:  python tools/probe_ml_api.py
# ============================================================

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

CLIENT_ID = os.getenv("ML_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "").strip()

TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
SEARCH_URL = "https://api.mercadolibre.com/sites/MLB/search"


def _post(url, dados):
    body = urllib.parse.urlencode(dados).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def _get(url, token=None):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        corpo = e.read().decode() or "{}"
        try:
            return e.code, json.loads(corpo)
        except Exception:
            return e.code, {"raw": corpo[:300]}


def main():
    print("=" * 78)
    print("SONDA — API do Mercado Livre")
    print("=" * 78)

    if not CLIENT_ID or not CLIENT_SECRET:
        print("\nFALTA CREDENCIAL. Acrescente em scripts/.env:")
        print("  ML_CLIENT_ID=...")
        print("  ML_CLIENT_SECRET=...")
        sys.exit(1)

    print(f"\nClient ID: {CLIENT_ID[:6]}…{CLIENT_ID[-4:]} "
          f"({len(CLIENT_ID)} chars) | secret: {len(CLIENT_SECRET)} chars")

    # ---- 1. token via client_credentials --------------------------------
    print("\n[1] grant_type=client_credentials")
    status, corpo = _post(TOKEN_URL, {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    if status != 200 or "access_token" not in corpo:
        print(f"    FALHOU (HTTP {status}): {json.dumps(corpo, ensure_ascii=False)[:400]}")
        print("\n    -> client_credentials NAO serve. O caminho passa a ser o fluxo")
        print("       authorization_code (login unico do Leandro). Me avise.")
        sys.exit(2)

    token = corpo["access_token"]
    print(f"    OK — token obtido ({len(token)} chars), expira em "
          f"{corpo.get('expires_in')}s, escopo: {corpo.get('scope')}")

    # ---- 2. busca aceita token de app? ----------------------------------
    print("\n[2] busca de produto com o token do app")
    consulta = "dom casmurro machado de assis livro"
    url = f"{SEARCH_URL}?{urllib.parse.urlencode({'q': consulta, 'limit': 5})}"
    status, dados = _get(url, token)
    print(f"    HTTP {status}")
    if status != 200:
        print(f"    corpo: {json.dumps(dados, ensure_ascii=False)[:400]}")
        print("\n    -> token de app recusado na busca.")
        sys.exit(3)

    resultados = dados.get("results", [])
    print(f"    OK — {dados.get('paging', {}).get('total', '?')} resultados totais, "
          f"{len(resultados)} retornados")

    # ---- 3. a resposta traz preco e URL de produto? ---------------------
    print("\n[3] campos uteis nos resultados")
    if not resultados:
        print("    NENHUM resultado — a query pode precisar de ajuste.")
        sys.exit(4)

    for i, item in enumerate(resultados[:5], 1):
        print(f"    {i}. {str(item.get('title'))[:56]}")
        print(f"       preco={item.get('price')} moeda={item.get('currency_id')} "
              f"cond={item.get('condition')}")
        print(f"       permalink={str(item.get('permalink'))[:78]}")

    faltando = [c for c in ("title", "price", "permalink")
                if resultados[0].get(c) in (None, "")]
    print("\n" + "=" * 78)
    if faltando:
        print(f"VEREDITO: resposta INCOMPLETA — faltam {faltando}")
        sys.exit(5)
    print("VEREDITO: client_credentials + busca + preco + permalink FUNCIONAM.")
    print("Da para trocar o scraping pela API em resolve_produto.")
    print("=" * 78)


if __name__ == "__main__":
    main()
