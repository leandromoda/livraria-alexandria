# ============================================================
# STEP — WIKIDATA ENRICH (fatos verificáveis + fontes)
# Livraria Alexandria
#
# Preenche `livros.wiki` e `autores.wiki` (JSON) a partir do Wikidata: título
# original, idioma, primeira publicação, gênero, série, prêmios, adaptações,
# links da Wikipedia/Open Library; e, para o autor, datas, país e Wikipedia.
# É o insumo da seção "Sobre a obra" do site.
#
# POR QUE ESTE STEP EXISTE
# ------------------------
# Depois do spam update de agosto/2026, a frente de *scaled content* ficou como
# a mais pesada: o corpo de cada página de livro é uma sinopse de LLM. Mais
# texto de LLM reforçaria o padrão; texto copiado da Wikipedia seria duplicata.
# Fato estruturado de fonte pública, exibido só quando existe, é informação que
# a sinopse não tem — e custa zero de quota LLM.
#
# COBERTURA MEDIDA (2026-10-05, sonda só-leitura, n=50 livros indexáveis
# sorteados com seed fixa, de uma população de 2.213)
# ---------------------------------------------------------------------
#   casou=21 (42%) | sem_candidato=19 | candidato sem P50=8 | autor nao casa=2
#   Entre os 21: ptwiki 17, P577 20, P136 18, P648 20, P4969 11, P166 7, P179 3.
#   Os 21 conferidos a mão: 0 falso positivo, todos com titulo 1,00.
#   n=50 da margem larga (~±14 pontos) — reconferir com o log agregado do G.
#
# CASAMENTO — DUAS FOLHAS, como na API do ML
# ------------------------------------------
# `wbsearchentities` nunca diz "não achei" para título comum: devolve o mais
# parecido. Por isso a obra só é aceita com (1) autor (P50) casando com o nosso
# e (2) título com `isbn_backfill.similaridade_titulo` >= LIMIAR_TITULO, a
# mesma régua bidirecional que reprova coletânea e box. Sem P50 = rejeitado:
# sem autor não há como distinguir obras homônimas.
#
# Não busca por ISBN: o Wikidata guarda P212 HIFENIZADO, e hifenizar exige a
# tabela de faixas do ISBN; além disso, edições são raras lá.
#
# AUTORES
# -------
# O QID do autor vem da obra casada (P50), nunca de busca por nome — nome de
# autor é ambíguo (dois "John Williams"), e a obra já resolveu a ambiguidade.
#
# RETOMÁVEL E SEM LAÇO
# --------------------
# `wiki_checado_em` é gravado também quando NÃO casa, então livro fora do
# Wikidata não volta à fila. Erro de rede não carimba. One-shot de propósito:
# os fatos de uma obra praticamente não mudam.
#
# SUPABASE
# --------
# PATCH só da coluna `wiki`, como o `isbn_backfill` faz com `isbn`. A coluna
# exige migração (scripts/sql/2026-10-05_wiki.sql); sem ela o dado fica local
# com `wiki_sync_em` NULL e sobe sozinho no primeiro passe depois da migração.
# ============================================================

import argparse
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone

import requests

from core.db import get_conn
from core.logger import log
from steps.isbn_backfill import similaridade_titulo

API = "https://www.wikidata.org/w/api.php"
# A Wikimedia exige User-Agent identificável com contato; UA genérico leva 403.
USER_AGENT = ("LivrariaAlexandriaBot/1.0 (https://livrariaalexandria.com.br; "
              "leandromoda1@gmail.com)")
TIMEOUT = (10, 30)
# Pausa entre chamadas. A API pede clientes "educados" e serializados; ~1 req/s
# não foi testado contra limite, mas ficou longe de 429 na sonda (~200 chamadas).
PAUSA = 0.6

LIMIAR_TITULO = 0.6       # mesma régua do isbn_backfill (calibrada lá)
MAX_ITENS = 5             # por lista (gêneros, prêmios, adaptações)
# pt-br antes de pt: no dry-run de 2026-10-05 a série do Mochileiro saiu como
# "À Boleia Pela Galáxia" (pt-PT) com pt-br disponível.
IDIOMAS_PT = ("pt-br", "pt")

# Propriedades lidas
P_AUTOR, P_TITULO, P_IDIOMA, P_PUBLICACAO = "P50", "P1476", "P407", "P577"
P_GENERO, P_SERIE, P_ORDEM, P_PREMIO = "P136", "P179", "P1545", "P166"
P_OPENLIB, P_DERIVADA, P_INSTANCIA = "P648", "P4969", "P31"
P_NASC, P_MORTE, P_PAIS = "P569", "P570", "P27"


class LimiteWikidata(Exception):
    """429/503 persistente — para o lote; não é veredito sobre o livro."""


# =========================
# SCHEMA
# =========================

COLUNAS = ("wiki", "wiki_qid", "wiki_checado_em", "wiki_sync_em")


def ensure_columns(conn):
    for tabela in ("livros", "autores"):
        existentes = {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
        for coluna in COLUNAS:
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} TEXT")
                log(f"[WIKI] coluna {tabela}.{coluna} criada")
    conn.commit()


# =========================
# FUNÇÕES PURAS (testadas sem rede)
# =========================

def _tokens(texto):
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {p for p in re.sub(r"[^a-z0-9 ]", " ", t).split() if len(p) > 2}


def autor_casa(nosso, rotulos):
    """O nome local casa com algum rótulo/alias do autor no Wikidata?

    Aceita contenção de tokens ("Tolkien" ⊂ "J. R. R. Tolkien") ou dois tokens
    em comum. Um token só não basta: "Silva", "King" e "Williams" sozinhos
    casariam autores diferentes.
    """
    a = _tokens(nosso)
    if not a:
        return False
    for r in rotulos:
        b = _tokens(r)
        if not b:
            continue
        if a <= b or b <= a or len(a & b) >= 2:
            return True
    return False


def rotulos(ent):
    """Labels + aliases nos idiomas que importam, como conjunto de strings."""
    out = set()
    for campo in ("labels", "aliases"):
        valores = ent.get(campo) or {}
        for lang in ("pt", "pt-br", "en", "es", "fr", "it", "de"):
            v = valores.get(lang)
            if isinstance(v, dict):
                out.add(v.get("value"))
            elif isinstance(v, list):
                out.update(i.get("value") for i in v)
    return {x for x in out if x}


def valores(ent, prop):
    """Valores (datavalue.value) de uma propriedade, na ordem do Wikidata."""
    out = []
    for c in (ent.get("claims") or {}).get(prop, []):
        if c.get("rank") == "deprecated":
            continue
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if v is not None:
            out.append(v)
    return out


def qids(ent, prop):
    return [v["id"] for v in valores(ent, prop) if isinstance(v, dict) and "id" in v]


def ano(ent, prop):
    """Menor ano de uma propriedade de data (P577/P569/P570), ou None.

    Menor, não primeiro: P577 costuma listar várias edições, e a primeira
    publicação é a que interessa. Ano negativo (a.C.) é devolvido como tal.
    """
    anos = []
    for v in valores(ent, prop):
        m = re.match(r"([+-])(\d+)-", (v or {}).get("time", "") if isinstance(v, dict) else "")
        if m:
            n = int(m.group(2))
            anos.append(-n if m.group(1) == "-" else n)
    return min(anos) if anos else None


def label(ent, permitir_en=True):
    """Melhor rótulo em pt-br/pt; en só se `permitir_en`. None se não houver.

    `permitir_en=False` para substantivo comum (gênero, prêmio, idioma, país,
    tipo de obra): no dry-run de 2026-10-05 saíram "science fiction comedy" e
    "comic novel" numa página em português. Nome próprio (título de
    adaptação, série) aceita o inglês, que costuma ser o nome real.
    """
    labels = (ent or {}).get("labels") or {}
    for lang in IDIOMAS_PT + (("en",) if permitir_en else ()):
        v = labels.get(lang)
        if v and v.get("value"):
            return v["value"]
    return None


def wikipedia(ent):
    sl = ent.get("sitelinks") or {}
    out = {}
    for lang in ("pt", "en"):
        s = sl.get(f"{lang}wiki")
        if s and s.get("url"):
            out[lang] = s["url"]
    return out


def escolher_obra(titulo, autor, obras, autores_ent):
    """Melhor obra que passa nas duas folhas: (qid, sim) ou (None, motivo).

    `obras`: {qid: entidade} candidatas; `autores_ent`: {qid: entidade} dos P50.
    Escolhe a de MAIOR similaridade entre as aprovadas, não a primeira.
    """
    com_autor = {q: e for q, e in obras.items() if qids(e, P_AUTOR)}
    if not com_autor:
        return None, "sem_obra_com_autor"
    melhor_q, melhor_sim, algum_autor = None, -1.0, False
    for q, e in com_autor.items():
        rot_aut = set()
        for a in qids(e, P_AUTOR):
            rot_aut |= rotulos(autores_ent.get(a) or {})
        if not autor_casa(autor, rot_aut):
            continue
        algum_autor = True
        titulos = rotulos(e) | {v.get("text") for v in valores(e, P_TITULO) if isinstance(v, dict)}
        sim = max((similaridade_titulo(titulo, t) for t in titulos if t), default=0.0)
        if sim > melhor_sim:
            melhor_q, melhor_sim = q, sim
    if not algum_autor:
        return None, "autor_nao_casa"
    if melhor_sim < LIMIAR_TITULO:
        return None, "titulo_divergente"
    return melhor_q, melhor_sim


def _rotulos_lista(qs, refs, permitir_en=False):
    out = []
    for q in qs:
        nome = label(refs.get(q), permitir_en)
        if nome and nome not in out:
            out.append(nome)
    return out[:MAX_ITENS]


def extrair_livro(ent, refs):
    """JSON publicado em `livros.wiki`. Chave ausente = sem dado (o site só
    renderiza o que existe — nunca "não informado")."""
    d = {"qid": ent["id"]}
    wp = wikipedia(ent)
    if wp:
        d["wikipedia"] = wp
    original = [v for v in valores(ent, P_TITULO) if isinstance(v, dict)]
    if original:
        d["titulo_original"] = original[0].get("text")
    idiomas = _rotulos_lista(qids(ent, P_IDIOMA), refs)
    if idiomas:
        d["idioma_original"] = idiomas[0]
    pub = ano(ent, P_PUBLICACAO)
    if pub is not None:
        d["publicacao"] = pub
    generos = _rotulos_lista(qids(ent, P_GENERO), refs)
    if generos:
        d["generos"] = generos
    premios = _rotulos_lista(qids(ent, P_PREMIO), refs)
    if premios:
        d["premios"] = premios

    # Série: só com rótulo. A ordem vem do qualificador P1545 do próprio claim.
    for c in (ent.get("claims") or {}).get(P_SERIE, []):
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        nome = label(refs.get(v["id"]), permitir_en=True) if isinstance(v, dict) else None
        if nome:
            serie = {"qid": v["id"], "nome": nome}
            ordem = (c.get("qualifiers") or {}).get(P_ORDEM)
            if ordem:
                serie["ordem"] = ordem[0].get("datavalue", {}).get("value")
            d["serie"] = serie
            break

    adapt = []
    for q in qids(ent, P_DERIVADA)[:MAX_ITENS]:
        r = refs.get(q)
        nome = label(r, permitir_en=True)
        if not nome:
            continue
        item = {"titulo": nome}
        tipo = _rotulos_lista(qids(r, P_INSTANCIA), refs)
        if tipo:
            item["tipo"] = tipo[0]
        a = ano(r, P_PUBLICACAO)
        if a is not None:
            item["ano"] = a
        adapt.append(item)
    if adapt:
        d["adaptacoes"] = adapt

    ol = [v for v in valores(ent, P_OPENLIB) if isinstance(v, str)]
    if ol:
        d["openlibrary"] = ol[0]
    return d


def extrair_autor(ent, refs):
    d = {"qid": ent["id"]}
    wp = wikipedia(ent)
    if wp:
        d["wikipedia"] = wp
    nasc, morte = ano(ent, P_NASC), ano(ent, P_MORTE)
    if nasc is not None:
        d["nascimento"] = nasc
    if morte is not None:
        d["morte"] = morte
    pais = _rotulos_lista(qids(ent, P_PAIS), refs)
    if pais:
        d["pais"] = pais[0]
    return d


def consultas(titulo):
    """Título inteiro e, se houver subtítulo, só a parte principal.

    Na sonda, 19 de 50 ficaram sem candidato; títulos com subtítulo raramente
    batem com o rótulo do Wikidata, que é o título curto da obra.
    """
    out = [titulo.strip()]
    curto = re.split(r"\s*[:—–]\s*|\s+-\s+", titulo, maxsplit=1)[0].strip()
    if curto and curto != out[0] and len(curto) >= 3:
        out.append(curto)
    return out


# =========================
# REDE
# =========================

_sessao = None


def _get(params):
    global _sessao
    if _sessao is None:
        _sessao = requests.Session()
        _sessao.headers.update({"User-Agent": USER_AGENT})
    params = {**params, "format": "json"}
    for tentativa, espera in enumerate((5, 20, 60)):
        r = _sessao.get(API, params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            time.sleep(PAUSA)
            return r.json()
        if r.status_code not in (429, 503):
            r.raise_for_status()
        time.sleep(int(r.headers.get("Retry-After") or espera))
    raise LimiteWikidata()


def _entidades(ids, props):
    out = {}
    ids = [i for i in dict.fromkeys(ids) if i]
    for i in range(0, len(ids), 50):  # limite da API por chamada
        out.update(_get({"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]),
                         "props": props, "languages": "pt|pt-br|en|es|fr|it|de"})
                   .get("entities", {}))
    return {q: e for q, e in out.items() if "missing" not in e}


def buscar(titulo, autor):
    """(entidade_obra, autores_ent) ou (None, motivo)."""
    cands = []
    for consulta in consultas(titulo):
        for lang in ("pt", "en"):
            r = _get({"action": "wbsearchentities", "search": consulta, "language": lang,
                      "uselang": lang, "type": "item", "limit": 10})
            cands += [x["id"] for x in r.get("search", [])]
    cands = list(dict.fromkeys(cands))[:30]
    if not cands:
        return None, "sem_candidato"
    obras = _entidades(cands, "labels|aliases|claims|sitelinks/urls")
    aut_ids = [a for e in obras.values() for a in qids(e, P_AUTOR)]
    autores_ent = _entidades(aut_ids, "labels|aliases|claims|sitelinks/urls") if aut_ids else {}
    q, info = escolher_obra(titulo, autor, obras, autores_ent)
    if not q:
        return None, info
    return (obras[q], autores_ent), None


def referencias(ent_obra, autores_ent):
    """Entidades citadas (idioma, gênero, série, prêmios, adaptações, país)."""
    ids = []
    for p in (P_IDIOMA, P_GENERO, P_SERIE, P_PREMIO):
        ids += qids(ent_obra, p)
    adapt = qids(ent_obra, P_DERIVADA)[:MAX_ITENS]
    for a in autores_ent.values():
        ids += qids(a, P_PAIS)
    refs = _entidades(ids + adapt, "labels|claims")
    tipos = [t for q in adapt for t in qids(refs.get(q) or {}, P_INSTANCIA)]
    refs.update(_entidades(tipos, "labels"))
    return refs


# =========================
# SUPABASE
# =========================

def _supabase():
    from steps.publish import SUPABASE_URL, HEADERS
    return SUPABASE_URL, HEADERS


def colunas_remotas():
    """{'livros': bool, 'autores': bool} — a coluna `wiki` existe no Supabase?

    Confere pelo OpenAPI do PostgREST, como manda o CLAUDE.md: PATCH com coluna
    ausente devolve 400 PGRST204.
    """
    url, headers = _supabase()
    try:
        spec = requests.get(f"{url}/rest/v1/", headers=headers, timeout=30).json()
        defs = spec.get("definitions", {})
        return {t: "wiki" in (defs.get(t, {}).get("properties") or {}) for t in ("livros", "autores")}
    except Exception as e:
        log(f"[WIKI] OpenAPI do Supabase ilegível ({type(e).__name__}) — sync adiado")
        return {"livros": False, "autores": False}


def sincronizar(conn, tabela, limite=500):
    """Sobe o `wiki` de quem ainda não foi sincronizado. Devolve quantos."""
    url, headers = _supabase()
    rows = conn.execute(f"""
        SELECT id, supabase_id, wiki FROM {tabela}
        WHERE wiki IS NOT NULL AND wiki_sync_em IS NULL AND supabase_id IS NOT NULL
        LIMIT ?
    """, (limite,)).fetchall()
    ok = 0
    for local_id, supabase_id, wiki in rows:
        try:
            r = requests.patch(f"{url}/rest/v1/{tabela}?id=eq.{supabase_id}",
                               headers={**headers, "Prefer": "return=minimal"},
                               json={"wiki": json.loads(wiki)}, timeout=30)
        except Exception as e:
            log(f"[WIKI] PATCH {tabela} falhou: {type(e).__name__}")
            continue
        if r.status_code in (200, 204):
            conn.execute(f"UPDATE {tabela} SET wiki_sync_em = ? WHERE id = ?",
                         (datetime.now(timezone.utc).isoformat(), local_id))
            ok += 1
        else:
            log(f"[WIKI] PATCH {tabela} {r.status_code}: {r.text[:120]}")
    conn.commit()
    return ok


# =========================
# SELEÇÃO
# =========================

# Indexável no site = is_publishable + oferta ativa com preço (livroIndexavel,
# lib/indexavel.ts). Localmente o espelho é status_publish=1 + preco_atual > 0:
# o books.db guarda uma oferta por livro e é a fonte do publish_ofertas.
_PENDENTES = """
    FROM livros
    WHERE wiki_checado_em IS NULL
      AND is_publishable = 1 AND status_publish = 1
      AND preco_atual > 0
      AND titulo IS NOT NULL AND TRIM(titulo) != ''
      AND autor IS NOT NULL AND TRIM(autor) != ''
"""


def fetch_pending(conn, limite):
    return conn.execute(
        f"SELECT id, titulo, autor {_PENDENTES} ORDER BY priority_score DESC LIMIT ?",
        (limite,)).fetchall()


def contar_pendentes(conn):
    return conn.execute(f"SELECT COUNT(*) {_PENDENTES}").fetchone()[0]


def _autores_do_livro(conn, livro_id):
    return conn.execute("""
        SELECT a.id, a.nome, a.wiki_checado_em FROM autores a
        JOIN livros_autores la ON la.autor_id = a.id
        WHERE la.livro_id = ?
    """, (livro_id,)).fetchall()


# =========================
# RUN
# =========================

def run(pacote=50, dry_run=False, sincronizar_supabase=True):
    """Enriquece até `pacote` livros indexáveis. Devolve quantos casaram."""
    log("Wikidata Enrich iniciado…")
    conn = get_conn()
    ensure_columns(conn)

    rows = fetch_pending(conn, pacote)
    pendentes = contar_pendentes(conn)
    stats = {"casados": 0, "sem_candidato": 0, "sem_obra_com_autor": 0,
             "autor_nao_casa": 0, "titulo_divergente": 0, "erro": 0, "autores": 0}
    agora = datetime.now(timezone.utc).isoformat()

    for i, (livro_id, titulo, autor) in enumerate(rows, 1):
        try:
            achado, motivo = buscar(titulo, autor)
            if achado:
                ent, autores_ent = achado
                refs = referencias(ent, autores_ent)
                dado = extrair_livro(ent, refs)
        except LimiteWikidata:
            log(f"[WIKI] Limite do Wikidata — lote parado em {i - 1}/{len(rows)}. "
                f"Retoma no próximo ciclo.")
            break
        except Exception as e:
            # Erro de rede/parse não é veredito: não carimba, tenta depois.
            stats["erro"] += 1
            print(f"[WIKI][{i:03d}/{len(rows):03d}] erro {type(e).__name__} — {titulo}")
            continue

        if not achado:
            stats[motivo] += 1
            if not dry_run:
                conn.execute("UPDATE livros SET wiki_checado_em = ? WHERE id = ?",
                             (agora, livro_id))
            continue

        stats["casados"] += 1
        print(f"[WIKI][{i:03d}/{len(rows):03d}] {dado['qid']} <- {titulo} "
              f"({len(dado) - 1} campos)")
        if dry_run:
            continue
        conn.execute("""UPDATE livros SET wiki = ?, wiki_qid = ?, wiki_checado_em = ?,
                        wiki_sync_em = NULL WHERE id = ?""",
                     (json.dumps(dado, ensure_ascii=False), dado["qid"], agora, livro_id))

        # Autores: casa cada P50 da obra com um autor nosso do mesmo livro.
        for a_id, a_nome, a_checado in _autores_do_livro(conn, livro_id):
            if a_checado:
                continue
            for q, a_ent in autores_ent.items():
                if q in qids(ent, P_AUTOR) and autor_casa(a_nome, rotulos(a_ent)):
                    conn.execute("""UPDATE autores SET wiki = ?, wiki_qid = ?,
                                    wiki_checado_em = ?, wiki_sync_em = NULL WHERE id = ?""",
                                 (json.dumps(extrair_autor(a_ent, refs), ensure_ascii=False),
                                  q, agora, a_id))
                    stats["autores"] += 1
                    break
        conn.commit()

    conn.commit()
    sync = ""
    if sincronizar_supabase and not dry_run:
        remotas = colunas_remotas()
        partes = []
        for tabela in ("livros", "autores"):
            if remotas.get(tabela):
                partes.append(f"{tabela}={sincronizar(conn, tabela)}")
            else:
                partes.append(f"{tabela}=coluna ausente (aplicar scripts/sql/2026-10-05_wiki.sql)")
        sync = " | sync " + ", ".join(partes)

    restantes = contar_pendentes(conn)
    conn.close()
    log(f"[WIKI] casados={stats['casados']} | sem_candidato={stats['sem_candidato']} | "
        f"sem_obra_com_autor={stats['sem_obra_com_autor']} | "
        f"autor_nao_casa={stats['autor_nao_casa']} | "
        f"titulo_divergente={stats['titulo_divergente']} | erro={stats['erro']} | "
        f"autores={stats['autores']} | lote={len(rows)} de {pendentes}{sync} | "
        f"restam={restantes}" + (" (dry-run)" if dry_run else ""))
    return stats["casados"]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Enriquece livros/autores com o Wikidata")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=50)
    a = p.parse_args()
    run(pacote=a.limit, dry_run=a.dry_run)
