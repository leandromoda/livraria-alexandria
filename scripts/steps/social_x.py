# ============================================================
# STEP — "LIVRO DO DIA" NO X (conta da Livraria Alexandria)
# Livraria Alexandria
#
# Gera, sob demanda, um post no formato `longo` (post principal + 3 a 6
# comentários) sobre um livro do catálogo. O último comentário — escrito aqui,
# não pelo LLM — leva à página do livro no site, com UTM. A publicação no X é
# MANUAL: o menu mostra cada parte para copiar e baixa a capa para anexar.
#
# Decisões do Leandro (2026-10-17), uma pergunta por vez:
#   - conta nova da livraria; publicação manual; gerador dentro deste repo;
#   - escolha: rodízio de categoria e, dentro dela, o mais popular (efeméride
#     suspensa por ora); sob demanda, sem fila diária;
#   - conteúdo: dados do site + conhecimento do modelo (Opus), com segunda
#     chamada que confere cada afirmação; só publica depois da aprovação;
#   - estilo: guia da @brazil1889 copiado e adaptado (agents/social_x/
#     guia-de-estilo.md), com tolerância de marketing (até 2 hashtags);
#   - capa anexada ao post principal.
#
# Origem do formato e do verificador mecânico: conceitos-filosoficos
# (estilo/formatos.md, formato 8, e ferramentas/verificar.py), copiados em
# 2026-10-17 e adaptados.
#
# Custo: 2 chamadas LLM por post (redação + verificação), +1 se o verificador
# mecânico pedir correção. Mesma quota PRO das sinopses, só quando chamado.
# ============================================================

import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from core.db import get_conn
from core.logger import log

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTE_REDATOR = REPO_ROOT / "agents" / "social_x" / "prompt.md"
AGENTE_VERIFICADOR = REPO_ROOT / "agents" / "social_x_verificar" / "prompt.md"
GUIA = REPO_ROOT / "agents" / "social_x" / "guia-de-estilo.md"
CAPAS_DIR = Path(__file__).resolve().parents[1] / "data" / "social" / "capas"

SITE = os.getenv("NEXT_PUBLIC_SITE_URL", "https://livrariaalexandria.com.br").rstrip("/")
UTM = "utm_source=x&utm_medium=social&utm_campaign=livro-do-dia"

# Limites do formato (guia, seção 5)
MIN_COMENTARIOS, MAX_COMENTARIOS = 3, 6     # do agente; +1 do convite com link
MAX_HASHTAGS = 2
TIMEOUT_LLM = 600


# =========================
# SCHEMA
# =========================

def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS social_posts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            livro_id      TEXT NOT NULL,
            slug          TEXT NOT NULL,
            titulo        TEXT,
            categoria     TEXT,
            status        TEXT NOT NULL,   -- aguardando | aprovado | publicado | descartado
            partes        TEXT NOT NULL,   -- JSON: partes do agente, sem numeração e sem convite
            verificacao   TEXT,            -- JSON do agente verificador
            problemas     TEXT,            -- JSON: verificação mecânica
            criado_em     TEXT,
            aprovado_em   TEXT,
            publicado_em  TEXT,
            link          TEXT
        )
    """)
    conn.commit()


# =========================
# VERIFICAÇÃO MECÂNICA (portada de conceitos-filosoficos/ferramentas/verificar.py)
# =========================

LIMITE_X = 280
URL_PESO = 23                      # o X conta qualquer URL como 23
MAX_PALAVRAS_FRASE = 25
NUMERACAO_RE = re.compile(r"\s*\b\d{1,2}/\d{1,2}\s*$")
URL_RE = re.compile(r"https?://\S+")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")
HASHTAG_RE = re.compile(r"(^|\s)#\w+")
# Faixas com peso 1 na contagem do X (twitter-text v3); o resto pesa 2.
FAIXAS_LEVES = [(0, 4351), (8192, 8205), (8208, 8223), (8242, 8247)]

PROIBIDAS = [
    "você sabia", "ninguém te conta", "ninguém conta", "não te ensinaram",
    "mudar sua vida", "mudar a sua vida", "imperdível", "obrigatório",
    "leitura obrigatória", "você precisa ler", "obra-prima absoluta",
    "basicamente", "simplesmente", "obviamente", "claramente", "jornada",
    "mindset", "ressignificar", "empoderar", "segue o fio", "fio:", "🧵",
    "abre o fio", "nos comentários", "continua abaixo", "curta e compartilhe",
    "e você, o que acha",
]


def tamanho_x(texto):
    total = URL_PESO * len(URL_RE.findall(texto))
    for ch in URL_RE.sub("", texto):
        cp = ord(ch)
        total += 1 if any(a <= cp <= b for a, b in FAIXAS_LEVES) else 2
    return total


def verificar_parte(texto, principal=False, convite=False):
    """Problemas mecânicos de uma parte JÁ numerada."""
    problemas = []
    n = tamanho_x(texto)
    if n > LIMITE_X:
        problemas.append(f"tamanho {n}/{LIMITE_X}")
    if EMOJI_RE.search(texto):
        problemas.append("contém emoji")
    tags = HASHTAG_RE.findall(texto)
    if tags and not principal:
        problemas.append("hashtag fora do post principal")
    if principal and len(tags) > MAX_HASHTAGS:
        problemas.append(f"{len(tags)} hashtags (máximo {MAX_HASHTAGS})")
    if "!" in texto:
        problemas.append("contém exclamação")
    if "..." in texto or "…" in texto:
        problemas.append("contém reticências")
    if re.search(r"\*[^*\s][^*]*\*", texto):
        problemas.append("marcação markdown (o X não formata)")
    sem_url = URL_RE.sub("", texto)
    for palavra in re.findall(r"\b[A-ZÀ-Ý]{4,}\b", sem_url):
        problemas.append(f"caixa alta: {palavra}")
    baixo = texto.lower()
    for termo in PROIBIDAS:
        if termo in baixo:
            problemas.append(f'expressão proibida: "{termo}"')
    if not convite:
        sem_numero = NUMERACAO_RE.sub("", sem_url)
        for frase in re.split(r"(?<=[.?:])\s+", sem_numero):
            if len(frase.split()) > MAX_PALAVRAS_FRASE:
                problemas.append(f'frase com {len(frase.split())} palavras: "{frase[:40]}…"')
    return problemas


# =========================
# MONTAGEM
# =========================

def url_livro(slug):
    return f"{SITE}/livros/{slug}?{UTM}"


def convite(slug):
    """Último comentário: escrito aqui, nunca pelo LLM (o link tem de estar certo)."""
    return f"Sinopse, detalhes da edição e onde comprar:\n{url_livro(slug)}"


def montar(partes, slug):
    """Partes como vão para o X: + convite com link, + controle 01/07 no fim.

    A numeração é gerada aqui, nunca guardada, para não sair errada se uma
    parte for cortada na revisão (mesma regra do conceitos-filosoficos).
    """
    todas = [NUMERACAO_RE.sub("", p).rstrip() for p in partes] + [convite(slug)]
    total = len(todas)
    largura = max(2, len(str(total)))
    return [f"{p}\n{i:0{largura}d}/{total:0{largura}d}" for i, p in enumerate(todas, 1)]


def problemas_mecanicos(partes, slug):
    """{n_parte: [problemas]} sobre o texto final; + problemas de estrutura em 0."""
    out = {}
    n_coment = len(partes) - 1
    if not (MIN_COMENTARIOS <= n_coment <= MAX_COMENTARIOS):
        out[0] = [f"{n_coment} comentário(s) do agente (esperado {MIN_COMENTARIOS} a {MAX_COMENTARIOS})"]
    finais = montar(partes, slug)
    for i, texto in enumerate(finais, 1):
        p = verificar_parte(texto, principal=(i == 1), convite=(i == len(finais)))
        if p:
            out[i] = p
    return out


# =========================
# ESCOLHA DO LIVRO
# =========================

# Elegível: indexável (publicado, publicável, oferta com preço — espelho local
# de livroIndexavel) e nunca usado num post (qualquer status, inclusive
# descartado, para não oferecer de novo o que já foi recusado).
_ELEGIVEIS = """
    FROM livros l
    WHERE l.status_publish = 1 AND l.is_publishable = 1
      AND l.preco_atual > 0
      AND l.slug IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM social_posts s WHERE s.livro_id = l.id)
"""


TAXONOMIA = Path(__file__).resolve().parents[1] / "data" / "taxonomy.json"


def _taxonomia():
    """slug -> (label, grupo). O rodízio é por GRUPO (23 em 2026-10-17, ex.:
    'Literatura Brasileira', 'Ficção Científica'): categoria fina (171) daria
    variedade de nome, não de leitura."""
    try:
        itens = json.loads(TAXONOMIA.read_text(encoding="utf-8"))
        return {i["slug"]: (i.get("label") or i["slug"], i.get("group") or "Outros") for i in itens}
    except Exception:
        return {}


def _chave_popularidade(row):
    """Ordem dentro do grupo. `priority_score` sozinho não separa: medido em
    2026-10-17, só 5 valores distintos (800–1000) entre 2.273 elegíveis — o
    desempate alfabético punha "1493" e "1968" na frente. Por isso, depois
    dele: página na Wikipédia em português (sinal real de livro conhecido),
    dados do Wikidata e, no fim, ordem estável embaralhada pelo id."""
    wiki = json.loads(row["wiki"]) if row["wiki"] else {}
    return (-(row["priority_score"] or 0),
            0 if (wiki.get("wikipedia") or {}).get("pt") else 1,
            0 if row["wiki_qid"] else 1,
            row["id"])


def escolher_livro(conn):
    """(livro_id, grupo) pelo rodízio: grupo de categoria usado há mais tempo
    (ou nunca) e, dentro dele, o livro mais conhecido."""
    tax = _taxonomia()
    livros = {r["id"]: r for r in conn.execute(
        f"SELECT l.id, l.priority_score, l.wiki, l.wiki_qid {_ELEGIVEIS}")}
    if not livros:
        return None, None
    # Categoria principal de cada elegível (primary_cat=1; senão a primeira).
    grupo_de = {}
    for lid, slug, prim in conn.execute("""
        SELECT livro_id, categoria_slug, primary_cat FROM livros_categorias_tematicas
        ORDER BY livro_id, primary_cat DESC, categoria_slug
    """):
        if lid in livros and lid not in grupo_de and slug in tax:
            grupo_de[lid] = tax[slug][1]
    ultimo_uso = dict(conn.execute(
        "SELECT categoria, MAX(criado_em) FROM social_posts GROUP BY categoria").fetchall())
    grupos = sorted({g for g in grupo_de.values()},
                    key=lambda g: (ultimo_uso.get(g) is not None, ultimo_uso.get(g) or "", g))
    for g in grupos:
        candidatos = [livros[lid] for lid, gg in grupo_de.items() if gg == g]
        if candidatos:
            return min(candidatos, key=_chave_popularidade)["id"], g
    # Sem categoria temática: só se nenhum categorizado sobrar.
    return min(livros.values(), key=_chave_popularidade)["id"], None


def dados_do_livro(conn, livro_id):
    l = conn.execute("""
        SELECT id, titulo, autor, slug, ano_publicacao, sinopse, wiki, imagem_url
        FROM livros WHERE id = ?
    """, (livro_id,)).fetchone()
    tax = _taxonomia()
    cats = [tax.get(r[0], (r[0], None))[0] for r in conn.execute("""
        SELECT categoria_slug FROM livros_categorias_tematicas
        WHERE livro_id = ? ORDER BY primary_cat DESC, categoria_slug
    """, (livro_id,))]
    autor_wiki = conn.execute("""
        SELECT a.wiki FROM autores a JOIN livros_autores la ON la.autor_id = a.id
        WHERE la.livro_id = ? AND a.wiki IS NOT NULL LIMIT 1
    """, (livro_id,)).fetchone()
    dados = {
        "titulo": l[1], "autor": l[2], "ano_da_edicao": l[4],
        "categorias": cats, "sinopse_publicada": l[5] or "",
    }
    if l[6]:
        w = json.loads(l[6])
        w.pop("qid", None)
        w.pop("wikipedia", None)
        w.pop("openlibrary", None)
        dados["fatos_wikidata"] = w
    if autor_wiki and autor_wiki[0]:
        a = json.loads(autor_wiki[0])
        dados["autor_wikidata"] = {k: v for k, v in a.items() if k in ("nascimento", "morte", "pais")}
    return dados, {"slug": l[3], "imagem_url": l[7], "titulo": l[1]}


# =========================
# LLM
# =========================

def _json_da_saida(saida):
    """Primeiro objeto JSON da saída do CLI (tolera cerca de código)."""
    texto = re.sub(r"```(?:json)?", "", saida or "")
    ini = texto.find("{")
    if ini < 0:
        raise ValueError("saída sem JSON")
    obj, _ = json.JSONDecoder().raw_decode(texto[ini:])
    return obj


def _redigir(dados, correcao=None, anterior=None):
    from core.claude_runner import run_agent
    extra = ("\n\n---\n\n## Guia de estilo\n\n" + GUIA.read_text(encoding="utf-8")
             + "\n\n---\n\n## Dados do livro\n\n" + json.dumps(dados, ensure_ascii=False, indent=2))
    if anterior:
        extra += ("\n\n---\n\n## Versão anterior\n\nEdite ESTA versão: mantenha o que está "
                  "certo e mude só o necessário para atender à correção.\n\n"
                  + "\n\n".join(f"[{i}] {p}" for i, p in enumerate(anterior, 1)))
    if correcao:
        extra += ("\n\n---\n\n## Correção pedida\n\nCorrija:\n\n" + correcao
                  + "\n\nAfirmação sem apoio: retire-a ou troque por algo que esteja nos dados. "
                    "Não a substitua por outra afirmação nova sem apoio.")
    ok, saida = run_agent(AGENTE_REDATOR, timeout=TIMEOUT_LLM, extra_context=extra)
    if not ok:
        raise RuntimeError(f"redator falhou: {saida[:200]}")
    obj = _json_da_saida(saida)
    if not obj.get("partes"):
        raise RuntimeError(f"redator não escreveu: {obj.get('motivo', 'sem motivo')}")
    return [p.strip() for p in obj["partes"] if p and p.strip()]


def _verificar(dados, partes):
    from core.claude_runner import run_agent
    numeradas = "\n\n".join(f"[{i}] {p}" for i, p in enumerate(partes, 1))
    extra = ("\n\n---\n\n## Dados do livro\n\n" + json.dumps(dados, ensure_ascii=False, indent=2)
             + "\n\n---\n\n## Partes do post\n\n" + numeradas)
    ok, saida = run_agent(AGENTE_VERIFICADOR, timeout=TIMEOUT_LLM, extra_context=extra)
    if not ok:
        raise RuntimeError(f"verificador falhou: {saida[:200]}")
    return _json_da_saida(saida)


# =========================
# AÇÕES
# =========================

def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _lista_mecanica(probs):
    return "\n".join(f"- parte {k}: {', '.join(v)}" for k, v in sorted(probs.items(), key=lambda x: int(x[0])))


def pedido_correcao(verif, probs):
    """Texto da correção a partir da verificação de afirmações e da mecânica.
    Vazio quando não há nada a corrigir."""
    itens = []
    for a in (verif or {}).get("afirmacoes", []):
        if a.get("apoio") == "sem_apoio":
            itens.append(f"- parte {a.get('parte')}: afirmação sem apoio — \"{a.get('texto')}\" "
                         f"({a.get('nota')})")
    if (verif or {}).get("spoiler"):
        itens.append("- o post revela mais do enredo do que a sinopse: retire o spoiler")
    if (verif or {}).get("citacao_duvidosa"):
        itens.append("- há citação entre aspas de procedência duvidosa: troque por paráfrase declarada ou retire")
    if probs:
        itens.append(_lista_mecanica(probs))
    return "\n".join(itens)


def _redigir_validado(dados, slug, correcao=None, anterior=None):
    """Redige (ou edita) e, se a mecânica reprovar, pede UMA correção mecânica."""
    partes = _redigir(dados, correcao=correcao, anterior=anterior)
    probs = problemas_mecanicos(partes, slug)
    if probs:
        log(f"[SOCIAL_X] Verificador mecânico pediu correção ({len(probs)} parte(s)); 1 nova tentativa.")
        partes = _redigir(dados, correcao=_lista_mecanica(probs), anterior=partes)
        probs = problemas_mecanicos(partes, slug)
    return partes, probs


def gerar():
    """Escolhe o próximo livro, redige, verifica e grava como 'aguardando'.

    Devolve o id do post ou None.
    """
    conn = get_conn()
    ensure_schema(conn)
    livro_id, categoria = escolher_livro(conn)
    if not livro_id:
        log("[SOCIAL_X] Nenhum livro elegível (indexável e ainda não usado).")
        conn.close()
        return None
    dados, info = dados_do_livro(conn, livro_id)
    log(f"[SOCIAL_X] Livro escolhido: {info['titulo']} (categoria: {categoria or '—'})")

    partes, probs = _redigir_validado(dados, info["slug"])
    verif = _verificar(dados, partes)
    cur = conn.execute("""
        INSERT INTO social_posts (livro_id, slug, titulo, categoria, status, partes,
                                  verificacao, problemas, criado_em)
        VALUES (?, ?, ?, ?, 'aguardando', ?, ?, ?, ?)
    """, (livro_id, info["slug"], info["titulo"], categoria,
          json.dumps(partes, ensure_ascii=False), json.dumps(verif, ensure_ascii=False),
          json.dumps(probs, ensure_ascii=False), _agora()))
    conn.commit()
    post_id = cur.lastrowid
    conn.close()
    sem_apoio = sum(1 for a in verif.get("afirmacoes", []) if a.get("apoio") == "sem_apoio")
    log(f"[SOCIAL_X] Post #{post_id} aguardando revisão — {len(partes)} partes | "
        f"sem apoio: {sem_apoio} | problemas mecânicos: {len(probs)}")
    return post_id


def corrigir(conn, post_id):
    """Edita um post 'aguardando' tirando o que os verificadores apontaram.

    Manda ao redator a versão atual + a lista do que corrigir, e revalida
    (mecânica + afirmações). Custa 2 chamadas (+1 se a mecânica reprovar).
    Devolve True se havia o que corrigir.
    """
    row = conn.execute("SELECT * FROM social_posts WHERE id=?", (post_id,)).fetchone()
    pedido = pedido_correcao(json.loads(row["verificacao"] or "{}"),
                             json.loads(row["problemas"] or "{}"))
    if not pedido:
        log(f"[SOCIAL_X] Post #{post_id}: nada a corrigir.")
        return False
    dados, info = dados_do_livro(conn, row["livro_id"])
    log(f"[SOCIAL_X] Corrigindo post #{post_id} ({pedido.count(chr(10)) + 1} ponto(s))…")
    partes, probs = _redigir_validado(dados, info["slug"], correcao=pedido,
                                      anterior=json.loads(row["partes"]))
    verif = _verificar(dados, partes)
    conn.execute("UPDATE social_posts SET partes=?, verificacao=?, problemas=? WHERE id=?",
                 (json.dumps(partes, ensure_ascii=False), json.dumps(verif, ensure_ascii=False),
                  json.dumps(probs, ensure_ascii=False), post_id))
    conn.commit()
    sem_apoio = sum(1 for a in verif.get("afirmacoes", []) if a.get("apoio") == "sem_apoio")
    log(f"[SOCIAL_X] Post #{post_id} corrigido — sem apoio: {sem_apoio} | "
        f"problemas mecânicos: {len(probs)}")
    return True


def baixar_capa(slug, imagem_url):
    """Baixa a capa para anexar ao post principal. Devolve o caminho ou None."""
    if not imagem_url:
        return None
    CAPAS_DIR.mkdir(parents=True, exist_ok=True)
    destino = CAPAS_DIR / f"{slug}.jpg"
    if destino.exists():
        return destino
    req = urllib.request.Request(imagem_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            destino.write_bytes(r.read())
        return destino
    except Exception as e:
        log(f"[SOCIAL_X] Capa não baixada ({type(e).__name__}) — o card do link ainda mostra a capa.")
        return None


def _copiar(texto):
    """Copia para a área de transferência do Windows. False se não conseguir."""
    try:
        subprocess.run(["clip"], input=texto.encode("utf-16-le"), check=True)
        return True
    except Exception:
        return False


# =========================
# MENU
# =========================

def _mostrar(row, input_fn):
    partes = json.loads(row["partes"])
    finais = montar(partes, row["slug"])
    print(f"\n=== Post #{row['id']} — {row['titulo']} (categoria: {row['categoria'] or '—'}) ===")
    for i, t in enumerate(finais, 1):
        rot = "post principal" if i == 1 else ("comentário com link" if i == len(finais) else "comentário")
        print(f"\n--- {i}/{len(finais)} {rot} ({tamanho_x(t)} caracteres) ---\n{t}")
    probs = json.loads(row["problemas"] or "{}")
    if probs:
        print("\n⚠ Problemas mecânicos:")
        for k, v in sorted(probs.items(), key=lambda x: int(x[0])):
            print(f"   parte {k}: {', '.join(v)}")
    verif = json.loads(row["verificacao"] or "{}")
    alertas = [a for a in verif.get("afirmacoes", []) if a.get("apoio") == "sem_apoio"]
    if alertas or verif.get("spoiler") or verif.get("citacao_duvidosa"):
        print("\n⚠ Verificador:")
        for a in alertas:
            print(f"   parte {a.get('parte')}: SEM APOIO — {a.get('texto')} ({a.get('nota')})")
        if verif.get("spoiler"):
            print("   possível SPOILER além da sinopse")
        if verif.get("citacao_duvidosa"):
            print("   citação de procedência duvidosa")
    else:
        n = len(verif.get("afirmacoes", []))
        print(f"\n✓ Verificador: {n} afirmação(ões), todas com apoio.")
    return finais


def _revisar(conn, input_fn):
    rows = conn.execute("SELECT * FROM social_posts WHERE status='aguardando' ORDER BY id").fetchall()
    if not rows:
        print("Nenhum post aguardando revisão.")
        return
    for row in rows:
        while True:
            _mostrar(row, input_fn)
            tem_o_que_corrigir = bool(pedido_correcao(json.loads(row["verificacao"] or "{}"),
                                                      json.loads(row["problemas"] or "{}")))
            opcoes = "[A]provar  [D]escartar  " + ("[C]orrigir (2 a 3 chamadas)  " if tem_o_que_corrigir else "")
            op = input_fn(f"\n{opcoes}[Enter] pular: ").strip().upper()
            if op == "C" and tem_o_que_corrigir:
                try:
                    corrigir(conn, row["id"])
                except Exception as e:
                    log(f"[SOCIAL_X] ERRO ao corrigir: {e}")
                row = conn.execute("SELECT * FROM social_posts WHERE id=?", (row["id"],)).fetchone()
                continue        # mostra a versão corrigida e pergunta de novo
            if op == "A":
                conn.execute("UPDATE social_posts SET status='aprovado', aprovado_em=? WHERE id=?",
                             (_agora(), row["id"]))
                log(f"[SOCIAL_X] Post #{row['id']} aprovado.")
            elif op == "D":
                conn.execute("UPDATE social_posts SET status='descartado' WHERE id=?", (row["id"],))
                log(f"[SOCIAL_X] Post #{row['id']} descartado (o livro não volta a ser oferecido).")
            conn.commit()
            break


def _publicar(conn, input_fn):
    row = conn.execute("SELECT * FROM social_posts WHERE status='aprovado' ORDER BY id LIMIT 1").fetchone()
    if not row:
        print("Nenhum post aprovado. Gere e revise um antes.")
        return
    finais = _mostrar(row, input_fn)
    img = conn.execute("SELECT imagem_url FROM livros WHERE id=?", (row["livro_id"],)).fetchone()
    capa = baixar_capa(row["slug"], img[0] if img else None)
    if capa:
        print(f"\nCapa para anexar ao post principal: {capa}")
        try:
            os.startfile(str(capa.parent))   # abre a pasta no Explorer
        except Exception:
            pass
    print("\nPublique no X: o post principal com a capa, depois cada comentário como "
          "resposta ao anterior.")
    for i, t in enumerate(finais, 1):
        input_fn(f"\nEnter para copiar a parte {i}/{len(finais)}…")
        print("  copiado." if _copiar(t) else f"  (não consegui copiar — selecione o texto acima)")
    link = input_fn("\nLink do post principal publicado (Enter = ainda não publiquei): ").strip()
    if link:
        conn.execute("UPDATE social_posts SET status='publicado', publicado_em=?, link=? WHERE id=?",
                     (_agora(), link, row["id"]))
        conn.commit()
        log(f"[SOCIAL_X] Post #{row['id']} registrado como publicado: {link}")


def menu(input_fn=input):
    conn = get_conn()
    ensure_schema(conn)
    conn.close()
    while True:
        conn = get_conn()
        cont = dict(conn.execute("SELECT status, COUNT(*) FROM social_posts GROUP BY status").fetchall())
        conn.close()
        print(f"""
=== LIVRO DO DIA — X (conta da livraria) ===
aguardando revisão: {cont.get('aguardando', 0)} | aprovados: {cont.get('aprovado', 0)} | publicados: {cont.get('publicado', 0)}

1 → Gerar próximo (escolhe o livro, redige e verifica — 2 a 3 chamadas LLM)
2 → Revisar pendentes (aprovar, corrigir ou descartar)
3 → Publicar o próximo aprovado (copiar partes + capa + registrar link)
0 → Voltar
""")
        op = input_fn("Opção: ").strip()
        if op == "0":
            return
        conn = get_conn()
        try:
            if op == "1":
                try:
                    gerar()
                except Exception as e:
                    log(f"[SOCIAL_X] ERRO ao gerar: {e}")
            elif op == "2":
                _revisar(conn, input_fn)
            elif op == "3":
                _publicar(conn, input_fn)
        finally:
            conn.close()
