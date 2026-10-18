"""IndexNow — avisa Bing, Yandex, Seznam e Naver das URLs novas ou alteradas.

Até 2026-10-18 o site só existia para o Google: nenhuma verificação no Bing,
nenhum envio a outro buscador. O IndexNow é o protocolo aberto que o Bing (e,
por tabela, DuckDuckGo, Yahoo e Ecosia, que usam o índice dele), Yandex, Seznam
e Naver aceitam — um POST com até 10.000 URLs, sem conta. A posse do domínio é
provada pela chave servida em `public/<KEY>.txt`.

A fonte é o **sitemap de produção**, não o `books.db`: ele já aplica as regras
de indexação do site (`lib/indexavel.ts`), então o que vai ao IndexNow é
exatamente o que o Google recebe. Envia:

- URL nova no sitemap;
- URL cujo `<lastmod>` mudou desde o último envio;
- URL que **saiu** do sitemap (noindex/404) — o IndexNow pede aviso de remoção
  também, para o buscador reconferir e descartar.

O estado (`url → lastmod enviado`) fica em `pipeline_state` via `kv_state`.
Só é gravado depois de o POST ser aceito (200/202): falha de rede não perde
nada, o próximo ciclo reenvia.

Roda no autopilot como manutenção (fora do accounting de progresso), igual ao
ISBN e ao Wikidata. Custo por ciclo: 1 GET do sitemap + 0 a N POSTs.
`INDEXNOW_POR_CICLO=0` desliga.
"""

import json
import os
import re

from core import kv_state
from core.logger import log

HOST = "livrariaalexandria.com.br"
KEY = "068232156bc734c2b806030fe90ce5ce"
KEY_LOCATION = f"https://{HOST}/{KEY}.txt"
SITEMAP_URL = f"https://{HOST}/sitemap.xml"
ENDPOINT = "https://api.indexnow.org/indexnow"

# Teto do protocolo por requisição.
LOTE_MAX = 10_000
POR_CICLO = int(os.getenv("INDEXNOW_POR_CICLO", "10000"))

CHAVE_ESTADO = "indexnow_enviados"

_URL_RE = re.compile(r"<url>(.*?)</url>", re.S)
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>")


def parse_sitemap(xml: str) -> dict:
    """`{url: lastmod}`; lastmod vazio quando o sitemap não traz (hubs)."""
    out = {}
    for bloco in _URL_RE.findall(xml):
        loc = _LOC_RE.search(bloco)
        if not loc:
            continue
        lm = _LASTMOD_RE.search(bloco)
        out[loc.group(1)] = lm.group(1) if lm else ""
    return out


def diff(enviados: dict, atual: dict) -> list:
    """URLs a enviar: novas, com lastmod alterado e removidas do sitemap."""
    mudou = [u for u, lm in atual.items() if enviados.get(u) != lm]
    saiu = [u for u in enviados if u not in atual]
    return mudou + saiu


def aplicar(enviados: dict, atual: dict, aceitas: list) -> dict:
    """Estado novo depois de `aceitas` irem com sucesso."""
    novo = dict(enviados)
    for u in aceitas:
        if u in atual:
            novo[u] = atual[u]
        else:
            novo.pop(u, None)
    return novo


def _carregar() -> dict:
    try:
        return json.loads(kv_state.get(CHAVE_ESTADO, "{}") or "{}")
    except (ValueError, TypeError):
        return {}


def _post(urls: list) -> int:
    import requests

    r = requests.post(
        ENDPOINT,
        json={"host": HOST, "key": KEY, "keyLocation": KEY_LOCATION, "urlList": urls},
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=60,
    )
    return r.status_code


def run(dry_run: bool = False) -> int:
    """Envia o que mudou. Devolve quantas URLs foram aceitas."""
    if POR_CICLO <= 0:
        return 0
    import requests

    try:
        resp = requests.get(SITEMAP_URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as e:
        log(f"[INDEXNOW] Sitemap indisponível — nada enviado: {e}")
        return 0

    atual = parse_sitemap(resp.text)
    if not atual:
        # Sitemap vazio é falha do site, não "tudo saiu": enviar remoção de
        # milhares de URLs por causa de um build quebrado seria o pior caso.
        log("[INDEXNOW] Sitemap sem URLs — abortando para não anunciar remoção em massa.")
        return 0

    enviados = _carregar()
    pendentes = diff(enviados, atual)[:POR_CICLO]
    if not pendentes:
        log(f"[INDEXNOW] Nada novo ({len(atual)} URLs no sitemap).")
        return 0
    if dry_run:
        log(f"[INDEXNOW] dry-run: {len(pendentes)} URLs seriam enviadas.")
        return 0

    aceitas = []
    for i in range(0, len(pendentes), LOTE_MAX):
        lote = pendentes[i:i + LOTE_MAX]
        try:
            status = _post(lote)
        except Exception as e:
            log(f"[INDEXNOW] ERRO de rede no lote de {len(lote)}: {e}")
            break
        # 200 = aceito; 202 = aceito, chave ainda em validação.
        if status in (200, 202):
            aceitas.extend(lote)
        else:
            # 403 chave inválida, 422 URL fora do host, 429 excesso.
            log(f"[INDEXNOW] Lote de {len(lote)} recusado: HTTP {status}")
            break

    if aceitas:
        kv_state.set(CHAVE_ESTADO, json.dumps(aplicar(enviados, atual, aceitas)))
    log(f"[INDEXNOW] Enviadas: {len(aceitas)} | Pendentes: {len(pendentes) - len(aceitas)} | Sitemap: {len(atual)}")
    return len(aceitas)


if __name__ == "__main__":
    import sys
    run(dry_run="--dry-run" in sys.argv)
