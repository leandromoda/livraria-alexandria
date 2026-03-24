"""
scripts/core/export_for_audit.py

Exporta livros PUBLICADOS no Supabase para auditoria pelo agente auditor.

Uso via menu do pipeline (opção 26) ou diretamente:
    python scripts/core/export_for_audit.py [--limit 100] [--format json|csv]

Caminhos canônicos de saída:
    scripts/data/audit_input.json   (padrão)
    scripts/data/audit_input.csv    (--format csv)

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

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)

REQUEST_TIMEOUT = 30
FIELDS          = "id,slug,titulo,autor,descricao,imagem_url"
FIELDNAMES      = ["id", "slug", "titulo", "autor", "sinopse", "imagem_url"]


def _load_env() -> tuple[str, str]:
    """Carrega .env e retorna (supabase_url, supabase_key)."""
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
    return url, key


def fetch_published(supabase_url: str, key: str, limit: int) -> list[dict]:
    """Busca livros publicados no Supabase via REST API."""
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
    }
    params = {
        "select":         FIELDS,
        "is_publishable": "eq.true",
        "status":         "eq.publish",
        "limit":          limit,
        "order":          "updated_at.desc",
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
            "sinopse":    b.get("descricao", ""),   # Supabase armazena sinopse como descricao
            "imagem_url": b.get("imagem_url", ""),
        }
        for b in books
    ]


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


def run(limit: int = 100, fmt: str = "json") -> None:
    """Entrypoint chamado pelo main.py (sem argparse)."""
    supabase_url, key = _load_env()
    if not supabase_url or not key:
        print("Erro: NEXT_PUBLIC_SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY não configuradas.")
        print("Configure scripts/.env ou variáveis de ambiente.")
        return

    print(f"Buscando até {limit} livros publicados no Supabase...")
    raw   = fetch_published(supabase_url, key, limit)
    books = normalize(raw)

    if not books:
        print("Nenhum livro publicado encontrado.")
        return

    output_path = _save(books, fmt)
    print(f"Exportados: {len(books)} livros → {output_path}")
    _print_next_steps(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Exporta livros publicados do Supabase para auditoria via Claude Code"
    )
    parser.add_argument("--limit",  type=int, default=100,
                        help="Número máximo de livros (default=100)")
    parser.add_argument("--format", type=str, default="json", choices=["json", "csv"],
                        help="Formato de saída: json (default) ou csv")
    args = parser.parse_args()
    run(limit=args.limit, fmt=args.format)


if __name__ == "__main__":
    main()
