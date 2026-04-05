# Offer Finder — Memory

This file is maintained by the agent across executions.
It stores patterns, failures, and observations to improve future runs.

Do NOT edit manually unless correcting outdated entries.

---

## search_patterns

Queries and strategies known to produce valid results.

| Pattern | Marketplace | Notes |
|---------|-------------|-------|
| `"{titulo}" "{autor}" livro site:amazon.com.br` | amazon | Default primary query — alta taxa de sucesso |
| `"{titulo}" "{autor}" livro site:mercadolivre.com.br` | mercadolivre | Default primary query — boa taxa de sucesso |
| `{isbn} site:amazon.com.br` | amazon | Alta precisão quando ISBN disponível |
| `{isbn} site:mercadolivre.com.br` | mercadolivre | Alta precisão quando ISBN disponível |
| `{autor} "{titulo}" livro amazon.com.br mercadolivre` | ambos | Fallback sem site: operator — útil quando busca restrita retorna vazio |

---

## failed_books

Books confirmed not found on any marketplace after exhaustive search.
Slugs listed here are skipped in future runs.

| slug | titulo | last_tried | marketplaces_tried |
|------|--------|------------|--------------------|
| a-casa-das-vozes | A Casa das Vozes | 2026-04-04 | amazon, mercadolivre |

---

## marketplace_notes

Structural observations about marketplace pages.

### Amazon BR

- Valid product URLs follow: `amazon.com.br/dp/{ASIN}` ou `amazon.com.br/{slug}/dp/{ASIN}`
- Search result pages: `amazon.com.br/s?k=...` — INVÁLIDO, descartar
- ISBN geralmente aparece na seção de detalhes do produto
- Título aparece em `<h1>`
- **BLOQUEIO**: amazon.com.br está bloqueado pelo proxy de egresso da rede (WebFetch retorna EGRESS_BLOCKED). Validação deve ser feita via metadata dos resultados da WebSearch.

### Mercado Livre

- Valid product URLs (em ordem de preferência):
  1. `produto.mercadolivre.com.br/MLB-{id}-{slug}_JM` — produto individual
  2. `mercadolivre.com.br/...../p/MLB{id}` — página de produto (catálogo)
  3. `mercadolivre.com.br/....../up/MLBU{id}` — listing de vendedor
- Listing pages: `lista.mercadolivre.com.br/...` — INVÁLIDO, descartar
- Título aparece em `<h1>`
- Autor pode aparecer na tabela de especificações do produto
- **BLOQUEIO**: produto.mercadolivre.com.br está bloqueado pelo proxy de egresso (WebFetch retorna EGRESS_BLOCKED). Validação deve ser feita via metadata dos resultados da WebSearch.

### Nota sobre validação sem WebFetch

Na execução de 2026-04-04, tanto amazon.com.br quanto mercadolivre.com.br retornaram EGRESS_BLOCKED no WebFetch.
A validação foi feita via metadata dos resultados de WebSearch (título + autor visíveis no snippet + padrão de URL de produto).
Confidence atribuída: `medium` para correspondência título + autor confirmada nos snippets.
Todos os registros desta execução devem ser revisados manualmente antes de publicação.

### Observações sobre títulos

- "A Carta Roubada" (Edgar Allan Poe) — disponível como livro físico standalone na Amazon (ISBN: 8525412775), mas no Mercado Livre aparece apenas em antologias/coletâneas. Status: partial.
- "A Casa das Vozes" (Donato Carrisi) — não encontrado em nenhum marketplace após 3 tentativas de busca. Possível que não esteja publicado no Brasil com este título ou esteja esgotado. Adicionado a failed_books.
- "1Q84" (Haruki Murakami) — na Amazon, o livro está dividido em 3 volumes separados; foi registrada a URL do Livro 1. No Mercado Livre, foi encontrada a Caixa completa (3 volumes).
