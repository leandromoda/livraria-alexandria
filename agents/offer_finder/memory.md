# Offer Finder — Memory

This file is maintained by the agent across executions.
It stores patterns, failures, and observations to improve future runs.

Do NOT edit manually unless correcting outdated entries.

---

## search_patterns

Queries and strategies known to produce valid results.

| Pattern | Marketplace | Notes |
|---------|-------------|-------|
| `"{titulo}" "{autor}" livro site:amazon.com.br` | amazon | Default primary query |
| `"{titulo}" "{autor}" livro site:mercadolivre.com.br` | mercadolivre | Default primary query |
| `{isbn} site:amazon.com.br` | amazon | High precision when ISBN available |
| `{isbn} site:mercadolivre.com.br` | mercadolivre | High precision when ISBN available |

---

## failed_books

Books confirmed not found on any marketplace after exhaustive search.
Slugs listed here are skipped in future runs.

| slug | titulo | last_tried | marketplaces_tried |
|------|--------|------------|--------------------|

---

## marketplace_notes

Structural observations about marketplace pages.

### Amazon BR

- Valid product URLs follow: `amazon.com.br/dp/{ASIN}` or `amazon.com.br/{slug}/dp/{ASIN}`
- Search result pages: `amazon.com.br/s?k=...` — INVALID, discard
- ISBN usually appears in product details section
- Title appears in `<h1>` element

### Mercado Livre

- Valid product URLs follow: `produto.mercadolivre.com.br/{slug}-{id}` or `mercadolivre.com.br/{category}/{slug}-{id}`
- Listing pages: `lista.mercadolivre.com.br/...` — INVALID, discard
- Title appears in `<h1>` element
- Author may appear in product specifications table
