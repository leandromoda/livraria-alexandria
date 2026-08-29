# ============================================================
# SONDA 2 — quais endpoints do ML o token de aplicacao alcanca
# Livraria Alexandria
#
# A sonda 1 mostrou: client_credentials OK, /sites/MLB/search -> 403.
# Esta varre as portas alternativas antes de desistir do caminho oficial.
# Somente GET, nao escreve nada.
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
CID = os.getenv("ML_CLIENT_ID", "").strip()
CSEC = os.getenv("ML_CLIENT_SECRET", "").strip()


def token():
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CID, "client_secret": CSEC}).encode()
    req = urllib.request.Request(
        "https://api.mercadolibre.com/oauth/token", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def get(url, tk):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tk}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()[:1200]
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode() or "")[:400]
    except Exception as e:
        return None, type(e).__name__


Q = urllib.parse.quote("dom casmurro machado de assis")

PORTAS = [
    ("busca do site (a que deu 403)",
     f"https://api.mercadolibre.com/sites/MLB/search?q={Q}&limit=3"),
    ("catalogo de produtos",
     f"https://api.mercadolibre.com/products/search?status=active&site_id=MLB&q={Q}"),
    ("produto por catalog_product_id",
     "https://api.mercadolibre.com/products/MLB15194094"),
    ("item por id (multiget)",
     "https://api.mercadolibre.com/items?ids=MLB1234567890"),
    ("dominios / predicao de categoria",
     f"https://api.mercadolibre.com/sites/MLB/domain_discovery/search?q={Q}"),
    ("categorias do site",
     "https://api.mercadolibre.com/sites/MLB/categories"),
    ("info do site",
     "https://api.mercadolibre.com/sites/MLB"),
    ("moedas",
     "https://api.mercadolibre.com/currencies/BRL"),
    # ⚠ /users/me devolve dados pessoais do titular da conta (CPF, endereco,
    # telefone). Fica fora desta sonda de proposito: ela existe para descobrir
    # quais portas abrem, e "o token e valido" ja esta provado por qualquer
    # outra porta que responda 200. Nao ha motivo para trazer PII ao terminal.
]


def main():
    if not CID or not CSEC:
        print("FALTA CREDENCIAL em scripts/.env")
        sys.exit(1)
    tk = token()
    print("token obtido.\n")
    print(f"{'porta':<38} {'status':<8} corpo (inicio)")
    print("-" * 100)
    ok = []
    for nome, url in PORTAS:
        st, corpo = get(url, tk)
        corpo_l = corpo.replace("\n", " ")[:52]
        print(f"{nome:<38} {str(st):<8} {corpo_l}")
        if st == 200:
            ok.append((nome, url, corpo))
    print("-" * 100)
    print(f"\n{len(ok)} de {len(PORTAS)} portas abertas.\n")
    for nome, url, corpo in ok:
        print("=" * 90)
        print("ABERTA:", nome)
        print(url)
        print(corpo[:700])
        print()


if __name__ == "__main__":
    main()
