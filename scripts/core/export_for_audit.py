"""
scripts/core/export_for_audit.py

Exporta livros PUBLICADOS no Supabase para auditoria pelo agente auditor.

Uso via menu do pipeline (opção 26) ou diretamente:
    python scripts/core/export_for_audit.py [--limit N] [--format json|csv]

Caminhos canônicos de saída:
    scripts/data/audit_input.json   (padrão)
    scripts/data/audit_input.csv    (--format csv)

Rotação automática (quando limit > 0):
    O offset do último lote é salvo em scripts/data/audit_state.json.
    Cada execução exporta um lote diferente, garantindo cobertura sistemática
    do catálogo ao longo de múltiplas rodadas.
    limit=0 (padrão) exporta todo o catálogo e não altera o estado de rotação.

Requer variáveis de ambiente (ou scripts/.env):
    NEXT_PUBLIC_SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY   (ou NEXT_PUBLIC_SUPABASE_ANON_KEY)
"""

import os
import sys
import csv
import json
import argparse
import requests
from datetime import datetime, timezone

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)

REQUEST_TIMEOUT = 30
FIELDS          = "id,slug,titulo,autor,descricao,imagem_url"
FIELDNAMES      = ["id", "slug", "titulo", "autor", "sinopse", "imagem_url"]
AUDIT_STATE     = os.path.join(SCRIPTS_ROOT, "data", "audit_state.json")


# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------

def _load_env() -> tuple[str, str]:
    """Carrega credenciais Supabase.

    Ordem de precedência:
    1. Variáveis de ambiente / .env  (NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)
    2. Fallback: constantes hardcoded em steps/publish.py (mesmas usadas pelo pipeline)
    """
    env_path = os.path.join(SCRIPTS_ROOT, ".env")
    if os.path.exists(env_path):
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            pass

    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
    )

    # Fallback: reutiliza as constantes já presentes no publish.py
    if not url or not key:
        try:
            sys.path.insert(0, SCRIPTS_ROOT)
            from steps.publish import SUPABASE_URL, SUPABASE_KEY
            url = url or SUPABASE_URL
            key = key or SUPABASE_KEY
        except ImportError:
            pass

    return url, key


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------

def fetch_published(supabase_url: str, key: str) -> list[dict]:
    """Busca TODOS os livros com status=publish no Supabase (ordem alfabética por título).

    Filtra apenas por status=publish — inclui livros com is_publishable=false
    que foram despublicados após a publicação inicial (ex: quality gate retroativo,
    auditor LLM, price monitor). O auditor deve cobrir esses livros também.
    """
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
    }
    params = {
        "select": FIELDS,
        "status": "eq.publish",
        "order":  "titulo.asc",
    }
    url = f"{supabase_url}/rest/v1/livros"

    try:
        r = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        print(f"Erro HTTP ao buscar livros: {e} — {r.text[:300]}")
        sys.exit(1)
    except Exception as e:
        print(f"Erro ao conectar ao Supabase: {e}")
        sys.exit(1)


def normalize(books: list[dict]) -> list[dict]:
    """Renomeia 'descricao' → 'sinopse' para alinhar com o prompt do auditor."""
    return [
        {
            "id":         b.get("id", ""),
            "slug":       b.get("slug", ""),
            "titulo":     b.get("titulo", ""),
            "autor":      b.get("autor", ""),
            "sinopse":    b.get("descricao", ""),
            "imagem_url": b.get("imagem_url", ""),
        }
        for b in books
    ]


# ---------------------------------------------------------------------------
# Rotação
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if os.path.exists(AUDIT_STATE):
        try:
            with open(AUDIT_STATE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"offset": 0}


def _save_state(offset: int, total: int) -> None:
    os.makedirs(os.path.dirname(AUDIT_STATE), exist_ok=True)
    state = {
        "offset":            offset,
        "total_at_last_run": total,
        "last_run":          datetime.now(timezone.utc).isoformat(),
    }
    with open(AUDIT_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _rotate(books: list[dict], limit: int) -> tuple[list[dict], int, int]:
    """
    Retorna (lote, offset_usado, proximo_offset).

    Aplica wrap-around: se o lote ultrapassa o fim do catálogo,
    completa com livros do início da lista.
    """
    total = len(books)
    state = _load_state()
    offset = state.get("offset", 0) % total   # segurança contra catálogo encolhido

    if offset + limit <= total:
        lote = books[offset : offset + limit]
    else:
        # wrap-around: pega o restante + início da lista
        lote = books[offset:] + books[: (offset + limit) % total]

    proximo = (offset + limit) % total
    return lote, offset, proximo


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _save(books: list[dict], fmt: str) -> str:
    """Salva books no caminho canônico. Retorna o caminho usado."""
    data_dir = os.path.join(SCRIPTS_ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)

    if fmt == "csv":
        output_path = os.path.join(data_dir, "audit_input.csv")
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(books)
    else:
        output_path = os.path.join(data_dir, "audit_input.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(books, f, ensure_ascii=False, indent=2)

    return output_path


def _print_next_steps(output_path: str) -> None:
    print()
    print("Próximos passos (Claude Code):")
    print(f"  1. Arquivo gerado: {output_path}")
    print()
    print('  2. No Claude Code, diga:')
    print('     "Leia scripts/data/audit_input.json, aplique as regras de')
    print('      agents/title_auditor/prompt.md e salve o resultado em')
    print('      scripts/data/blacklist.json"')
    print()
    print("  3. Revise: scripts/data/blacklist.json")
    print()
    print("  4. Pipeline menu → opção 25 (Aplicar Blacklist)")
    print("     ou: python scripts/steps/apply_blacklist.py [--dry-run]")


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------

def run(limit: int = 0, fmt: str = "json") -> None:
    """Entrypoint chamado pelo main.py (sem argparse).

    limit=0 (padrão) → exporta todo o catálogo; não altera o estado de rotação.
    limit>0           → exporta um lote com rotação automática.
    """
    supabase_url, key = _load_env()
    if not supabase_url or not key:
        print("Erro: NEXT_PUBLIC_SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY não configuradas.")
        print("Configure scripts/.env ou variáveis de ambiente.")
        return

    print("Buscando catálogo publicado no Supabase...")
    all_books = normalize(fetch_published(supabase_url, key))
    total = len(all_books)

    if not total:
        print("Nenhum livro publicado encontrado.")
        return

    if limit == 0:
        # Catálogo completo — sem rotação
        lote = all_books
        print(f"Exportando catálogo completo: {total} livros")
    else:
        lote, offset_usado, proximo_offset = _rotate(all_books, limit)
        lotes_total = -(-total // limit)   # ceil division
        lote_atual  = offset_usado // limit + 1
        print(f"Rotação: lote {lote_atual}/{lotes_total} "
              f"(livros {offset_usado + 1}–{offset_usado + len(lote)} de {total})")
        print(f"Próxima execução começará no offset {proximo_offset}")
        _save_state(proximo_offset, total)

    output_path = _save(lote, fmt)
    print(f"Exportados: {len(lote)} livros → {output_path}")
    _print_next_steps(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Exporta livros publicados do Supabase para auditoria via Claude Code"
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Tamanho do lote (padrão=0: catálogo completo). Com limit>0, "
             "a rotação é automática via audit_state.json.",
    )
    parser.add_argument(
        "--format", type=str, default="json", choices=["json", "csv"],
        help="Formato de saída: json (padrão) ou csv",
    )
    args = parser.parse_args()
    run(limit=args.limit, fmt=args.format)


if __name__ == "__main__":
    main()
