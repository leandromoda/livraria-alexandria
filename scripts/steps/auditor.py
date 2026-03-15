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
REPORT_DIR = os.path.join(SCRIPTS_ROOT, "data")

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
# Relatório JSON
# ---------------------------------------------------------------------------

def save_report(data: dict) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    mode = data.get("mode", "audit")
    filename = f"audit_{mode}_{ts}.json"
    path = os.path.join(REPORT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"\nRelatório salvo: {path}")
    return path


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

    if args.mode == "connectivity":
        data = run_connectivity(conn, dry_run=args.dry_run)
    elif args.mode == "content":
        data = run_content_audit(conn, limit=args.limit, dry_run=args.dry_run)
    else:
        log.error("Modo inválido. Use --connectivity ou --content")
        return

    data["generated_at"] = _now_iso()
    data["dry_run"] = args.dry_run
    report_path = save_report(data)
    log.info(f"Relatório: {report_path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auditor do site Livraria Alexandria"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # Modo connectivity
    sub.add_parser("connectivity", help="Testa conectividade de infra (sem LLM)")

    # Modo content
    content_p = sub.add_parser("content", help="Audita coerência editorial via LLM")
    content_p.add_argument("--limit", type=int, default=20,
                            help="Número de livros a auditar (default=20)")

    # Flag global
    parser.add_argument("--dry-run", action="store_true",
                        help="Executa sem aplicar despublicação")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    run(args)
