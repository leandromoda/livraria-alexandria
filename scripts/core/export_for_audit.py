"""
scripts/core/export_for_audit.py

Exporta livros PUBLICADOS no Supabase para JSON de input do agente auditor.

Uso:
    python scripts/core/export_for_audit.py --limit 100 --output audit_input.json

O JSON gerado deve ser colado no Claude chat junto com o prompt em:
    agents/title_auditor/prompt.md

Requer variáveis de ambiente (ou scripts/.env):
    NEXT_PUBLIC_SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY   (ou NEXT_PUBLIC_SUPABASE_ANON_KEY)
"""

import os
import sys
import json
import argparse
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)

REQUEST_TIMEOUT = 30
FIELDS = "id,slug,titulo,autor,descricao,imagem_url"


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
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    params = {
        "select": FIELDS,
        "is_publishable": "eq.true",
        "status": "eq.publish",
        "limit": limit,
        "order": "updated_at.desc",
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
    normalized = []
    for b in books:
        normalized.append({
            "id":         b.get("id", ""),
            "slug":       b.get("slug", ""),
            "titulo":     b.get("titulo", ""),
            "autor":      b.get("autor", ""),
            "sinopse":    b.get("descricao", ""),   # Supabase armazena sinopse como descricao
            "imagem_url": b.get("imagem_url", ""),
        })
    return normalized


def main():
    parser = argparse.ArgumentParser(
        description="Exporta livros publicados do Supabase para auditoria via Claude chat"
    )
    parser.add_argument("--limit", type=int, default=100,
                        help="Número máximo de livros (default=100)")
    parser.add_argument("--output", type=str, default="audit_input.json",
                        help="Arquivo de saída (default=audit_input.json)")
    args = parser.parse_args()

    supabase_url, key = _load_env()
    if not supabase_url or not key:
        print("Erro: NEXT_PUBLIC_SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY não configuradas.")
        print("Configure scripts/.env ou variáveis de ambiente.")
        sys.exit(1)

    print(f"Buscando até {args.limit} livros publicados no Supabase...")
    raw = fetch_published(supabase_url, key, args.limit)
    books = normalize(raw)

    if not books:
        print("Nenhum livro publicado encontrado.")
        sys.exit(0)

    output_path = (
        os.path.join(SCRIPTS_ROOT, "data", args.output)
        if not os.path.isabs(args.output)
        else args.output
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)

    print(f"Exportados: {len(books)} livros → {output_path}")
    print()
    print("Próximo passo:")
    print("  1. Abra o Claude chat (claude.ai)")
    print("  2. Cole o conteúdo de: agents/title_auditor/prompt.md")
    print(f"  3. Cole o conteúdo de: {output_path}")
    print("  4. Salve a resposta em: scripts/data/blacklist.json")
    print("  5. Execute: python scripts/steps/apply_blacklist.py")


if __name__ == "__main__":
    main()
