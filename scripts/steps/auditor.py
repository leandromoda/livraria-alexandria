"""
scripts/steps/auditor.py

Step de auditoria do site com dois modos:

    --connectivity   Testa conectividade de infra (sem LLM)
    --content        Audita coerência editorial via LLM (com --limit N)

Flags:
    --limit N        Número de livros a auditar por run (modo --content, default=20)
    --dry-run        Executa auditoria mas NÃO aplica despublicação

Despublicação automática: severity=medium ou high
  → SQLite: is_publishable=0, status_publish=0
  → Supabase: PATCH is_publishable=0
"""

import os
import sys
import json
import time
import uuid
import argparse
import sqlite3
import requests
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Path setup — permite rodar como `python steps/auditor.py` ou via main.py
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from core.db import get_connection
from core.logger import log as _core_log
from core.markdown_executor import _call_llm
from core.markdown_memory import save_memory, load_memory


class _Logger:
    """Wrapper para compatibilizar log.info/warning/error com core.logger."""
    def __init__(self, name: str):
        self._name = name
    def info(self, msg: str):
        _core_log(f"[{self._name}] {msg}")
    def warning(self, msg: str):
        _core_log(f"[{self._name}][WARNING] {msg}")
    def error(self, msg: str):
        _core_log(f"[{self._name}][ERROR] {msg}")

log = _Logger("auditor")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
SITE_BASE_URL = "https://livrariaalexandria.com.br"
SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

SEVERITY_UNPUBLISH = {"medium", "high"}   # threshold para despublicação
REQUEST_TIMEOUT = 10                       # segundos
REPORT_DIR = Path(SCRIPTS_ROOT) / "data" / "logs"
LIST_MIN_MEMBERS = 5                       # mínimo de livros publicados por lista

GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
TITLE_VERIFY_API_DELAY = 0.35             # segundos entre chamadas Google Books API

# ---------------------------------------------------------------------------
# Tabela audit_log — criada automaticamente se não existir
# ---------------------------------------------------------------------------
DDL_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id           TEXT PRIMARY KEY,
    livro_id     TEXT NOT NULL,
    slug         TEXT NOT NULL,
    mode         TEXT NOT NULL,
    severity     TEXT,
    issues       TEXT,
    action_taken TEXT,
    audited_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

DDL_CONNECTIVITY_LOG = """
CREATE TABLE IF NOT EXISTS connectivity_log (
    id           TEXT PRIMARY KEY,
    check_type   TEXT NOT NULL,
    target       TEXT NOT NULL,
    status_code  INTEGER,
    latency_ms   INTEGER,
    ok           INTEGER NOT NULL,
    detail       TEXT,
    checked_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def ensure_audit_tables(conn: sqlite3.Connection) -> None:
    conn.execute(DDL_AUDIT_LOG)
    conn.execute(DDL_CONNECTIVITY_LOG)
    conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _supabase_headers(use_service_key: bool = False) -> dict:
    key = SUPABASE_SERVICE_KEY if use_service_key else SUPABASE_ANON_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _http_get(url: str, allow_redirects: bool = True) -> tuple[int | None, int, str]:
    """Retorna (status_code, latency_ms, detail)."""
    try:
        t0 = time.monotonic()
        r = requests.get(url, timeout=REQUEST_TIMEOUT,
                         allow_redirects=allow_redirects,
                         headers={"User-Agent": "AlexandriaAuditor/1.0"})
        latency_ms = int((time.monotonic() - t0) * 1000)
        return r.status_code, latency_ms, ""
    except requests.exceptions.Timeout:
        return None, REQUEST_TIMEOUT * 1000, "timeout"
    except requests.exceptions.ConnectionError as e:
        return None, 0, f"connection_error: {e}"
    except Exception as e:
        return None, 0, f"error: {e}"


def _http_head(url: str) -> tuple[int | None, int, str]:
    try:
        t0 = time.monotonic()
        r = requests.head(url, timeout=REQUEST_TIMEOUT,
                          allow_redirects=True,
                          headers={"User-Agent": "AlexandriaAuditor/1.0"})
        latency_ms = int((time.monotonic() - t0) * 1000)
        return r.status_code, latency_ms, ""
    except requests.exceptions.Timeout:
        return None, REQUEST_TIMEOUT * 1000, "timeout"
    except Exception as e:
        return None, 0, f"error: {e}"


def _save_connectivity_result(conn: sqlite3.Connection, check_type: str,
                               target: str, status_code: int | None,
                               latency_ms: int, ok: bool, detail: str) -> None:
    conn.execute(
        """INSERT INTO connectivity_log
           (id, check_type, target, status_code, latency_ms, ok, detail)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), check_type, target, status_code,
         latency_ms, 1 if ok else 0, detail)
    )
    conn.commit()


# ---------------------------------------------------------------------------
# MODO 1: --connectivity
# ---------------------------------------------------------------------------

def run_connectivity(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """
    Testa conectividade de infra. Sem LLM.
    Retorna dict com resultados para relatório.
    """
    results = []

    def check(label: str, check_type: str, url: str,
              method: str = "get", expected_status: int | list = 200,
              allow_redirects: bool = True) -> dict:
        if method == "head":
            status, latency_ms, detail = _http_head(url)
        else:
            status, latency_ms, detail = _http_get(url, allow_redirects=allow_redirects)

        if isinstance(expected_status, int):
            expected_status = [expected_status]

        ok = status in expected_status
        icon = "✓" if ok else "✗"
        log.info(f"  [{icon}] {label} → {status} ({latency_ms}ms) {detail}")

        if not dry_run:
            _save_connectivity_result(conn, check_type, url, status,
                                      latency_ms, ok, detail)
        return {
            "label": label,
            "check_type": check_type,
            "url": url,
            "status_code": status,
            "latency_ms": latency_ms,
            "ok": ok,
            "detail": detail,
        }

    log.info("=== CONNECTIVITY CHECK ===")

    # 1. Supabase health
    log.info("--- Supabase ---")
    if SUPABASE_URL:
        results.append(check(
            "Supabase: livros endpoint",
            "supabase_table",
            f"{SUPABASE_URL}/rest/v1/livros?limit=1",
        ))
        results.append(check(
            "Supabase: autores endpoint",
            "supabase_table",
            f"{SUPABASE_URL}/rest/v1/autores?limit=1",
        ))
        results.append(check(
            "Supabase: listas endpoint",
            "supabase_table",
            f"{SUPABASE_URL}/rest/v1/listas?limit=1",
        ))
    else:
        log.warning("  SUPABASE_URL não configurada — pulando checks Supabase")

    # 2. Rotas do site — amostra de slugs reais do SQLite
    log.info("--- Site routes ---")
    results.append(check("Home", "site_route", SITE_BASE_URL))
    results.append(check("Hub livros", "site_route", f"{SITE_BASE_URL}/livros"))
    results.append(check("Hub listas", "site_route", f"{SITE_BASE_URL}/listas"))
    results.append(check("Hub categorias", "site_route", f"{SITE_BASE_URL}/categorias"))
    results.append(check("Hub autores", "site_route", f"{SITE_BASE_URL}/autores"))
    results.append(check("Ofertas", "site_route", f"{SITE_BASE_URL}/ofertas"))
    results.append(check("Admin", "site_route", f"{SITE_BASE_URL}/admin"))

    # Slugs reais de livros publicados
    rows = conn.execute(
        "SELECT slug FROM livros WHERE status_publish=1 AND slug IS NOT NULL LIMIT 3"
    ).fetchall()
    for (slug,) in rows:
        results.append(check(
            f"Livro: {slug}",
            "site_route_livro",
            f"{SITE_BASE_URL}/livros/{slug}",
        ))

    # Slugs reais de autores publicados
    autor_rows = conn.execute(
        "SELECT slug FROM autores WHERE status_publish=1 AND slug IS NOT NULL LIMIT 2"
    ).fetchall()
    for (slug,) in autor_rows:
        results.append(check(
            f"Autor: {slug}",
            "site_route_autor",
            f"{SITE_BASE_URL}/autores/{slug}",
        ))

    # 3. Click API
    log.info("--- Click API ---")
    click_row = conn.execute(
        "SELECT id FROM livros WHERE status_publish=1 AND offer_url IS NOT NULL LIMIT 1"
    ).fetchone()
    if click_row:
        results.append(check(
            "Click API redirect",
            "api_click",
            f"{SITE_BASE_URL}/api/click/{click_row[0]}",
            expected_status=[301, 302, 307, 308],
            allow_redirects=False,
        ))
    else:
        log.warning("  Nenhum livro com offer_url para testar click API")

    # 4. Imagens — amostra de imagem_url
    log.info("--- Images ---")
    img_rows = conn.execute(
        "SELECT slug, imagem_url FROM livros WHERE status_publish=1 "
        "AND imagem_url IS NOT NULL AND imagem_url != '' LIMIT 5"
    ).fetchall()
    for slug, img_url in img_rows:
        results.append(check(
            f"Imagem: {slug}",
            "image_url",
            img_url,
            method="head",
            expected_status=[200, 301, 302],
        ))

    # Sumário
    total = len(results)
    failures = [r for r in results if not r["ok"]]
    log.info(f"\nResultado: {total - len(failures)}/{total} OK | {len(failures)} falhas")
    for f in failures:
        log.warning(f"  FALHA: {f['label']} → {f['status_code']} {f['detail']}")

    return {"mode": "connectivity", "total": total,
            "ok": total - len(failures), "failures": len(failures),
            "results": results}


# ---------------------------------------------------------------------------
# MODO 2: --content (LLM)
# ---------------------------------------------------------------------------

AUDIT_PROMPT_TEMPLATE = """Você é um auditor editorial rigoroso de uma livraria online.

Analise os dados do livro abaixo e determine se a SINOPSE é coerente com o título e autor.

TÍTULO: {titulo}
AUTOR: {autor}
ANO: {ano}
SINOPSE:
{sinopse}

CONTEÚDO RENDERIZADO NA PÁGINA (extraído do site):
{rendered_text}

TAREFA:
1. A sinopse é coerente com o título e o autor? (sem alucinações, sem contradições, sem informações implausíveis)
2. O conteúdo renderizado na página bate com os dados cadastrados?
3. Há outros problemas editoriais graves? (sinopse vaga demais, fora do contexto literário, etc.)

Responda SOMENTE com JSON válido, sem markdown, sem explicações fora do JSON:

{{
  "coherent": true|false,
  "severity": "none"|"low"|"medium"|"high",
  "issues": ["lista de problemas encontrados, vazia se nenhum"],
  "summary": "resumo curto do diagnóstico (máx 1 frase)"
}}

severity:
  none   = tudo ok
  low    = problema menor, não compromete
  medium = problema relevante, merece revisão
  high   = sinopse absurda, errada ou alucinada — despublicação necessária
"""


def _fetch_rendered_page(url: str) -> str:
    """Busca página do site e extrai texto relevante via BeautifulSoup."""
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT,
                         headers={"User-Agent": "AlexandriaAuditor/1.0"})
        if r.status_code != 200:
            return f"[HTTP {r.status_code}]"
        soup = BeautifulSoup(r.text, "html.parser")

        # Remove scripts, styles e nav
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Extrai texto principal
        main = soup.find("main") or soup.find("article") or soup.body
        if main:
            text = main.get_text(separator=" ", strip=True)
        else:
            text = soup.get_text(separator=" ", strip=True)

        # Limita para não explodir o prompt
        return text[:2000]
    except Exception as e:
        return f"[erro ao buscar página: {e}]"


def _parse_llm_audit_response(raw: str) -> dict:
    """Extrai JSON da resposta do LLM com fallback seguro."""
    try:
        # Remove possíveis blocos markdown
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        return json.loads(cleaned)
    except Exception:
        return {
            "coherent": False,
            "severity": "low",
            "issues": ["LLM retornou resposta não parseável"],
            "summary": "Falha no parse da resposta LLM",
        }


def _despublish_sqlite(conn: sqlite3.Connection, livro_id: str, slug: str) -> None:
    conn.execute(
        "UPDATE livros SET is_publishable=0, status_publish=0, "
        "updated_at=? WHERE id=?",
        (_now_iso(), livro_id)
    )
    conn.commit()
    log.info(f"    [SQLite] Despublicado: {slug}")


def _despublish_supabase(slug: str) -> bool:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        log.warning("    [Supabase] Credenciais não configuradas — skip PATCH")
        return False
    try:
        url = f"{SUPABASE_URL}/rest/v1/livros?slug=eq.{slug}"
        r = requests.patch(
            url,
            headers={**_supabase_headers(use_service_key=True),
                     "Prefer": "return=minimal"},
            json={"is_publishable": False},
            timeout=REQUEST_TIMEOUT,
        )
        ok = r.status_code in (200, 204)
        log.info(f"    [Supabase] PATCH {slug} → {r.status_code}")
        return ok
    except Exception as e:
        log.error(f"    [Supabase] Erro ao despublicar {slug}: {e}")
        return False


def _save_audit_entry(conn: sqlite3.Connection, livro_id: str, slug: str,
                      severity: str, issues: list, action: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO audit_log
           (id, livro_id, slug, mode, severity, issues, action_taken, audited_at)
           VALUES (?, ?, ?, 'content', ?, ?, ?, ?)""",
        (str(uuid.uuid4()), livro_id, slug, severity,
         json.dumps(issues, ensure_ascii=False), action, _now_iso())
    )
    conn.commit()


def run_content_audit(conn: sqlite3.Connection, limit: int = 20,
                      dry_run: bool = False) -> dict:
    """
    Audita coerência editorial dos livros publicados via LLM.
    """
    log.info(f"=== CONTENT AUDIT (limit={limit}, dry_run={dry_run}) ===")

    rows = conn.execute(
        """SELECT id, slug, titulo, autor, ano_publicacao, sinopse, descricao
           FROM livros
           WHERE status_publish=1 AND is_publishable=1
             AND sinopse IS NOT NULL AND sinopse != ''
           ORDER BY RANDOM()
           LIMIT ?""",
        (limit,)
    ).fetchall()

    if not rows:
        log.warning("Nenhum livro publicado com sinopse encontrado.")
        return {"mode": "content", "audited": 0, "results": []}

    results = []
    despublished = []

    for livro_id, slug, titulo, autor, ano, sinopse, descricao in rows:
        log.info(f"\n→ Auditando: {titulo} ({slug})")

        # 1. Busca conteúdo renderizado
        page_url = f"{SITE_BASE_URL}/livros/{slug}"
        rendered_text = _fetch_rendered_page(page_url)
        log.info(f"   Página extraída: {len(rendered_text)} chars")

        # 2. Diff simples: sinopse do DB vs texto da página
        sinopse_in_page = sinopse[:80].strip() in rendered_text if sinopse else False
        diff_issues = []
        if not sinopse_in_page:
            diff_issues.append("Sinopse do DB não encontrada no conteúdo renderizado")
        if titulo and titulo.lower() not in rendered_text.lower():
            diff_issues.append("Título do DB não encontrado na página")

        # 2b. Validação de imagem
        imagem_url_row = conn.execute(
            "SELECT imagem_url FROM livros WHERE id=?", (livro_id,)
        ).fetchone()
        imagem_url = imagem_url_row[0] if imagem_url_row else None
        if imagem_url:
            img_status, _, _ = _http_head(imagem_url)
            if img_status is None or img_status not in (200, 301, 302):
                diff_issues.append(f"Imagem inválida ou inacessível (HTTP {img_status}): {imagem_url}")
                log.warning(f"   Imagem FALHOU: {img_status}")

        # 3. Auditoria LLM
        prompt = AUDIT_PROMPT_TEMPLATE.format(
            titulo=titulo or "(sem título)",
            autor=autor or "(sem autor)",
            ano=ano or "N/A",
            sinopse=sinopse or "(sem sinopse)",
            rendered_text=rendered_text,
        )

        raw_response = _call_llm(prompt)
        audit = _parse_llm_audit_response(raw_response)

        # Merge issues de diff + LLM
        all_issues = diff_issues + audit.get("issues", [])
        severity = audit.get("severity", "low")

        # Eleva severity se há diff crítico
        if diff_issues and severity == "none":
            severity = "low"

        log.info(f"   Severity: {severity} | Issues: {all_issues}")
        log.info(f"   LLM summary: {audit.get('summary', '')}")

        # 4. Ação
        action = "none"
        if severity in SEVERITY_UNPUBLISH:
            if dry_run:
                action = "would_despublish"
                log.info(f"   [DRY-RUN] Despublicação não aplicada")
            else:
                _despublish_sqlite(conn, livro_id, slug)
                sup_ok = _despublish_supabase(slug)
                action = "despublished" if sup_ok else "despublished_sqlite_only"
                despublished.append(slug)

        # 5. Salva no audit_log
        if not dry_run:
            _save_audit_entry(conn, livro_id, slug, severity, all_issues, action)

        results.append({
            "slug": slug,
            "titulo": titulo,
            "severity": severity,
            "issues": all_issues,
            "summary": audit.get("summary", ""),
            "action": action,
            "page_url": page_url,
        })

    log.info(f"\nAuditoria concluída: {len(rows)} livros | "
             f"Despublicados: {len(despublished)}")

    return {
        "mode": "content",
        "audited": len(rows),
        "despublished": len(despublished),
        "despublished_slugs": despublished,
        "results": results,
    }


# ---------------------------------------------------------------------------
# MODO 3: --list  (sem LLM)
# ---------------------------------------------------------------------------

DDL_LIST_STATUS = """
CREATE TABLE IF NOT EXISTS listas (
    id           TEXT PRIMARY KEY,
    slug         TEXT,
    titulo       TEXT,
    status_publish INTEGER DEFAULT 0
);
"""


def run_list_audit(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """
    Verifica coerência das listas SEO publicadas. Sem LLM.

    Critérios:
    - Lista com 0 membros publicados → despublica (status_publish=0)
    - Lista com < LIST_MIN_MEMBERS membros publicados → sinaliza como needs_refresh
    """
    log.info(f"=== LIST AUDIT (dry_run={dry_run}) ===")

    rows = conn.execute(
        "SELECT id, slug, titulo FROM listas WHERE status_publish=1"
    ).fetchall()

    if not rows:
        log.warning("Nenhuma lista publicada encontrada no banco local.")
        return {"mode": "list", "total": 0, "results": []}

    results = []
    despublished = []
    needs_refresh = []

    for lista_id, slug, titulo in rows:
        # Conta membros que ainda estão publicados
        count_row = conn.execute(
            """SELECT COUNT(*) FROM lista_livros ll
               JOIN livros l ON l.id = ll.livro_id
               WHERE ll.lista_id = ? AND l.status_publish = 1""",
            (lista_id,)
        ).fetchone()
        published_count = count_row[0] if count_row else 0

        if published_count == 0:
            status = "empty"
            log.info(f"  [✗] {titulo} ({slug}) → 0 membros publicados → despublica")
            if not dry_run:
                conn.execute(
                    "UPDATE listas SET status_publish=0, updated_at=? WHERE id=?",
                    (_now_iso(), lista_id)
                )
                conn.commit()
                # PATCH Supabase
                if SUPABASE_URL and SUPABASE_SERVICE_KEY:
                    try:
                        url = f"{SUPABASE_URL}/rest/v1/listas?slug=eq.{slug}"
                        requests.patch(
                            url,
                            headers={**_supabase_headers(use_service_key=True),
                                     "Prefer": "return=minimal"},
                            json={"status_publish": False},
                            timeout=REQUEST_TIMEOUT,
                        )
                    except Exception as e:
                        log.error(f"  Supabase PATCH lista {slug}: {e}")
            despublished.append(slug)
        elif published_count < LIST_MIN_MEMBERS:
            status = "needs_refresh"
            log.info(f"  [!] {titulo} ({slug}) → {published_count} membros (< {LIST_MIN_MEMBERS})")
            needs_refresh.append(slug)
        else:
            status = "ok"
            log.info(f"  [✓] {titulo} ({slug}) → {published_count} membros")

        results.append({
            "slug": slug,
            "titulo": titulo,
            "published_members": published_count,
            "status": status,
        })

    log.info(
        f"\nListas: OK={sum(1 for r in results if r['status']=='ok')} | "
        f"Needs refresh={len(needs_refresh)} | "
        f"Despublicadas={len(despublished)} | "
        f"Total={len(rows)}"
    )

    return {
        "mode": "list",
        "total": len(rows),
        "despublished": len(despublished),
        "despublished_slugs": despublished,
        "needs_refresh_slugs": needs_refresh,
        "results": results,
    }


# ---------------------------------------------------------------------------
# MODO 4: --author-bios  (sem LLM)
# ---------------------------------------------------------------------------

def check_author_bios(conn: sqlite3.Connection) -> dict:
    """
    Verifica autores publicados sem bio. Sem LLM — apenas relatório.
    Não despublica. Registra em audit_log para rastreabilidade.
    """
    log.info("=== AUTHOR BIO CHECK ===")

    rows = conn.execute(
        """SELECT id, slug, nome FROM autores
           WHERE status_publish=1
             AND (bio IS NULL OR TRIM(bio) = '')"""
    ).fetchall()

    total_published = conn.execute(
        "SELECT COUNT(*) FROM autores WHERE status_publish=1"
    ).fetchone()[0]

    slugs_sem_bio = [r[1] for r in rows]

    if rows:
        log.info(f"  {len(rows)}/{total_published} autores publicados sem bio:")
        for _, slug, nome in rows:
            log.info(f"    - {nome} ({slug})")
    else:
        log.info(f"  Todos os {total_published} autores publicados têm bio. OK.")

    # Salva no audit_log como severity=low (sem despublicação)
    for autor_id, slug, nome in rows:
        conn.execute(
            """INSERT OR REPLACE INTO audit_log
               (id, livro_id, slug, mode, severity, issues, action_taken, audited_at)
               VALUES (?, ?, ?, 'author_bio', 'low', ?, 'none', ?)""",
            (
                str(uuid.uuid4()),
                autor_id,
                slug,
                json.dumps([f"Autor publicado sem bio: {nome}"], ensure_ascii=False),
                _now_iso(),
            )
        )
    if rows:
        conn.commit()

    return {
        "mode": "author_bio",
        "total_published": total_published,
        "without_bio": len(rows),
        "slugs_sem_bio": slugs_sem_bio,
    }


# ---------------------------------------------------------------------------
# MODO 5: --title-verify  (Google Books API + LLM)
# ---------------------------------------------------------------------------

TITLE_VERIFY_PROMPT = """Você é um auditor bibliográfico especializado.
Avalie se o livro abaixo corresponde a uma obra real e publicada.

Título: {titulo}
Autor: {autor}
Descrição disponível: {descricao}

Responda SOMENTE com JSON válido, sem markdown:

{{"real": true|false, "confidence": "high"|"medium"|"low", "reason": "motivo em 1 frase"}}

Critérios:
- real=true: título e autor formam uma combinação que corresponde a livro real publicado
- real=false: combinação improvável, incoerente ou claramente inventada
- confidence: quão seguro você está da avaliação
"""


def _google_books_lookup(titulo: str, autor: str) -> str:
    """
    Consulta Google Books API e retorna nível de correspondência:
    'exact' | 'partial' | 'none' | 'api_unavailable'
    """
    if not GOOGLE_BOOKS_API_KEY:
        return "api_unavailable"

    query = f"intitle:{titulo}"
    if autor:
        query += f"+inauthor:{autor}"

    params = {
        "q":          query,
        "maxResults": 3,
        "fields":     "items(volumeInfo(title,authors))",
        "key":        GOOGLE_BOOKS_API_KEY,
    }

    try:
        resp = requests.get(GOOGLE_BOOKS_URL, params=params,
                            timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": "AlexandriaAuditor/1.0"})
        if resp.status_code != 200:
            log.warning(f"  Google Books API HTTP {resp.status_code} para: {titulo}")
            return "api_unavailable"

        items = resp.json().get("items", [])
        if not items:
            return "none"

        titulo_norm = titulo.lower().strip()
        autor_norm  = (autor or "").lower().strip()

        for item in items:
            vi            = item.get("volumeInfo", {})
            api_titulo    = vi.get("title", "").lower().strip()
            api_autores   = " ".join(vi.get("authors", [])).lower()

            titulo_match = titulo_norm in api_titulo or api_titulo in titulo_norm
            autor_match  = autor_norm and (
                any(part in api_autores for part in autor_norm.split() if len(part) > 3)
            )

            if titulo_match and (not autor_norm or autor_match):
                return "exact"
            if titulo_match or autor_match:
                return "partial"

        return "none"

    except Exception as e:
        log.warning(f"  Google Books lookup falhou: {e}")
        return "api_unavailable"


def _llm_verify_title(titulo: str, autor: str, descricao: str) -> dict:
    """Usa LLM para verificar veracidade do par título+autor. Retorna dict com real/confidence/reason."""
    descricao_curta = (descricao or "")[:400]
    prompt = TITLE_VERIFY_PROMPT.format(
        titulo=titulo or "(sem título)",
        autor=autor or "(sem autor)",
        descricao=descricao_curta or "(sem descrição)",
    )
    try:
        raw = _call_llm(prompt)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        data = json.loads(cleaned)
        return {
            "real":       bool(data.get("real", True)),
            "confidence": str(data.get("confidence", "low")),
            "reason":     str(data.get("reason", "")),
        }
    except Exception as e:
        log.warning(f"  LLM title verify falhou: {e}")
        return {"real": True, "confidence": "low", "reason": "llm_error"}


def _combine_title_severity(api_match: str, llm_real: bool, llm_confidence: str) -> str:
    """
    Combina sinais da API e LLM em severity final.

    Matrix:
    exact   + real=true            → none   (verificado)
    exact   + real=false           → low    (discrepância menor)
    partial + real=true            → low    (provável real)
    partial + real=false           → medium (suspeito)
    none    + real=true, conf=high → low    (obra obscura mas plausível)
    none    + real=true, conf!=high→ low    (benefício da dúvida)
    none    + real=false           → high   (provável alucinação)
    unavail + real=true            → low    (só LLM, benefício da dúvida)
    unavail + real=false           → medium (max sem API)
    """
    if api_match == "exact":
        return "none" if llm_real else "low"

    if api_match == "partial":
        return "low" if llm_real else "medium"

    if api_match == "none":
        return "low" if llm_real else "high"

    # api_unavailable
    return "low" if llm_real else "medium"


def _fetch_books_for_title_verify(conn: sqlite3.Connection,
                                   scope: str, limit: int) -> list:
    """Busca livros do SQLite conforme scope: all | published | pipeline."""
    if scope == "published":
        where = "WHERE l.status_publish = 1"
    elif scope == "pipeline":
        where = "WHERE l.status_publish = 0"
    else:  # all
        where = ""

    # Exclui livros já verificados recentemente (audit_log mode=title_verify, last 30 dias)
    query = f"""
        SELECT l.id, l.slug, l.titulo, l.autor, l.descricao,
               l.status_publish, l.is_publishable
        FROM livros l
        {where}
        {"AND" if where else "WHERE"} l.titulo IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM audit_log al
              WHERE al.livro_id = l.id
                AND al.mode = 'title_verify'
                AND al.audited_at >= datetime('now', '-30 days')
          )
        ORDER BY RANDOM()
        LIMIT ?
    """
    return conn.execute(query, (limit,)).fetchall()


def _apply_title_action(conn: sqlite3.Connection, livro_id: str, slug: str,
                         severity: str, status_publish: int,
                         dry_run: bool) -> str:
    """Aplica ação conforme severity. Retorna string de action tomada."""
    if severity not in ("medium", "high"):
        return "none"

    if severity == "medium":
        if dry_run:
            return "would_flag_review"
        conn.execute(
            "UPDATE livros SET reactivation_pending=1, updated_at=? WHERE id=?",
            (_now_iso(), livro_id)
        )
        conn.commit()
        return "flagged_review"

    # severity == high
    if dry_run:
        return "would_block" if status_publish == 0 else "would_despublish"

    if status_publish == 1:
        _despublish_sqlite(conn, livro_id, slug)
        _despublish_supabase(slug)
        return "despublished"
    else:
        conn.execute(
            "UPDATE livros SET is_publishable=0, updated_at=? WHERE id=?",
            (_now_iso(), livro_id)
        )
        conn.commit()
        return "blocked_pipeline"


def run_title_verify(conn: sqlite3.Connection, limit: int = 50,
                     scope: str = "all", dry_run: bool = False) -> dict:
    """
    Verifica veracidade dos títulos via Google Books API + LLM.
    Escopo configurável: all | published | pipeline.
    """
    log.info(f"=== TITLE VERIFY (limit={limit}, scope={scope}, dry_run={dry_run}) ===")

    if not GOOGLE_BOOKS_API_KEY:
        log.warning("  GOOGLE_BOOKS_API_KEY não configurada — verificação apenas via LLM (max severity=medium)")

    rows = _fetch_books_for_title_verify(conn, scope, limit)

    if not rows:
        log.info("Nenhum livro elegível para verificação de título.")
        return {"mode": "title_verify", "verified": 0, "results": []}

    results      = []
    blocked      = []
    despublished = []

    for livro_id, slug, titulo, autor, descricao, status_publish, is_publishable in rows:
        log.info(f"\n→ {titulo} / {autor or '(sem autor)'} [{slug}]")

        # 1. Google Books API
        api_match = _google_books_lookup(titulo or "", autor or "")
        log.info(f"   API match: {api_match}")
        time.sleep(TITLE_VERIFY_API_DELAY)

        # 2. LLM
        llm = _llm_verify_title(titulo or "", autor or "", descricao or "")
        log.info(f"   LLM: real={llm['real']} confidence={llm['confidence']} → {llm['reason']}")

        # 3. Severity
        severity = _combine_title_severity(api_match, llm["real"], llm["confidence"])
        log.info(f"   Severity: {severity}")

        # 4. Ação
        action = _apply_title_action(conn, livro_id, slug, severity,
                                     status_publish, dry_run)
        if "despublish" in action:
            despublished.append(slug)
        if "block" in action:
            blocked.append(slug)

        # 5. audit_log
        issues = []
        if api_match == "none":
            issues.append(f"Título não encontrado no Google Books: '{titulo}'")
        if api_match == "partial":
            issues.append(f"Correspondência parcial no Google Books para: '{titulo}'")
        if not llm["real"]:
            issues.append(f"LLM indica livro não real (confidence={llm['confidence']}): {llm['reason']}")

        if not dry_run:
            conn.execute(
                """INSERT OR REPLACE INTO audit_log
                   (id, livro_id, slug, mode, severity, issues, action_taken, audited_at)
                   VALUES (?, ?, ?, 'title_verify', ?, ?, ?, ?)""",
                (str(uuid.uuid4()), livro_id, slug, severity,
                 json.dumps(issues, ensure_ascii=False), action, _now_iso())
            )
            conn.commit()

        results.append({
            "slug":       slug,
            "titulo":     titulo,
            "autor":      autor,
            "api_match":  api_match,
            "llm_real":   llm["real"],
            "llm_conf":   llm["confidence"],
            "llm_reason": llm["reason"],
            "severity":   severity,
            "action":     action,
        })

    ok_count  = sum(1 for r in results if r["severity"] in ("none", "low"))
    sus_count = sum(1 for r in results if r["severity"] == "medium")
    hal_count = sum(1 for r in results if r["severity"] == "high")

    log.info(
        f"\nTitle verify concluído: {len(results)} livros | "
        f"OK/baixo={ok_count} | Suspeito={sus_count} | Alucinação={hal_count} | "
        f"Despublicados={len(despublished)} | Bloqueados pipeline={len(blocked)}"
    )

    return {
        "mode":               "title_verify",
        "scope":              scope,
        "verified":           len(results),
        "ok_low":             ok_count,
        "suspicious":         sus_count,
        "hallucinated":       hal_count,
        "despublished":       len(despublished),
        "blocked_pipeline":   len(blocked),
        "despublished_slugs": despublished,
        "blocked_slugs":      blocked,
        "results":            results,
    }


# ---------------------------------------------------------------------------
# Relatório JSON — numeração sequencial em data/logs/
# ---------------------------------------------------------------------------

def _next_sequence(log_dir: Path) -> int:
    existing = sorted(log_dir.glob("[0-9][0-9][0-9][0-9]_*.json"))
    if not existing:
        return 1
    return int(existing[-1].name[:4]) + 1


def save_report(data: dict) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    seq = _next_sequence(REPORT_DIR)
    mode = data.get("mode", "audit")
    filename = f"{seq:04d}_audit_{mode}.json"
    path = REPORT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"\nRelatório salvo: {path}")
    return str(path)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    """Entrypoint chamado pelo main.py ou diretamente."""
    # Carrega .env se disponível
    env_path = os.path.join(SCRIPTS_ROOT, ".env")
    if os.path.exists(env_path):
        from dotenv import load_dotenv
        load_dotenv(env_path)
        # Atualiza globals pós-load
        global SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY
        SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
        SUPABASE_ANON_KEY = os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
        SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    conn = get_connection()
    ensure_audit_tables(conn)

    dry_run = getattr(args, "dry_run", False)

    if args.mode == "connectivity":
        data = run_connectivity(conn, dry_run=dry_run)
    elif args.mode == "content":
        data = run_content_audit(conn, limit=args.limit, dry_run=dry_run)
    elif args.mode == "list":
        data = run_list_audit(conn, dry_run=dry_run)
    elif args.mode == "author-bios":
        data = check_author_bios(conn)
    elif args.mode == "title-verify":
        data = run_title_verify(
            conn,
            limit=getattr(args, "limit", 50),
            scope=getattr(args, "scope", "all"),
            dry_run=dry_run,
        )
    else:
        log.error("Modo inválido. Use connectivity, content, list, author-bios ou title-verify")
        return

    data["generated_at"] = _now_iso()
    data["dry_run"] = dry_run
    report_path = save_report(data)
    log.info(f"Relatório: {report_path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auditor do site Livraria Alexandria"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # Modo connectivity (sem LLM)
    sub.add_parser("connectivity", help="Testa conectividade de infra (sem LLM)")

    # Modo content (LLM)
    content_p = sub.add_parser("content", help="Audita coerência editorial via LLM")
    content_p.add_argument("--limit", type=int, default=20,
                            help="Número de livros a auditar (default=20)")

    # Modo list (sem LLM)
    sub.add_parser("list", help="Verifica coerência das listas SEO (sem LLM)")

    # Modo author-bios (sem LLM)
    sub.add_parser("author-bios", help="Verifica autores publicados sem bio (sem LLM)")

    # Modo title-verify (Google Books API + LLM)
    title_p = sub.add_parser(
        "title-verify",
        help="Verifica veracidade dos títulos via Google Books API + LLM"
    )
    title_p.add_argument(
        "--limit", type=int, default=50,
        help="Número de livros a verificar (default=50)"
    )
    title_p.add_argument(
        "--scope", choices=["all", "published", "pipeline"], default="all",
        help="Escopo: all (padrão) | published | pipeline"
    )

    # Flag global
    parser.add_argument("--dry-run", action="store_true",
                        help="Executa sem aplicar despublicação")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    run(args)
