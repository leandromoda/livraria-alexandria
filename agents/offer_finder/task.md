# Offer Finder — Task

## Task Name

find_valid_offers

---

## Startup — Ask for X

Before doing anything else, ask the user:

> Quantos livros deseja processar nesta execução? (padrão: 100)

Accept the user's answer as `X`.

If the user provides no answer or confirms the default: use `X = 100`.

If the user provides a value ≤ 0 or non-numeric: ask again.

---

## Inputs

The agent collects all inputs autonomously:

```
runtime:
  X            — integer collected from user (default: 100)
  marketplaces — ["amazon", "mercadolivre"] (fixed)
```

`book_list` is NOT provided by the caller — the agent fetches it
from Supabase as described in **Preconditions** below.

---

## Preconditions

Before starting the search loop:

1. **Read memory** — read `agents/offer_finder/memory.md` to load
   known search patterns and previously failed books.

2. **Fetch book_list from Supabase** — query the `livros` table
   joined with `ofertas` to find published books without active offers:

   ```sql
   SELECT
     l.id          AS supabase_id,
     l.slug,
     l.titulo,
     l.autor,
     l.isbn
   FROM livros l
   LEFT JOIN ofertas o ON o.livro_id = l.id AND o.ativa = true
   WHERE o.id IS NULL
   ORDER BY l.titulo ASC
   LIMIT {X};
   ```

   Use the Supabase REST API (anon key) via WebFetch:

   ```
   GET {NEXT_PUBLIC_SUPABASE_URL}/rest/v1/livros
       ?select=id,slug,titulo,autor,isbn,ofertas!left(id,ativa)
       &ofertas.ativa=eq.true
       &order=titulo.asc
       &limit={X}
   Headers:
     apikey: {NEXT_PUBLIC_SUPABASE_ANON_KEY}
     Authorization: Bearer {NEXT_PUBLIC_SUPABASE_ANON_KEY}
   ```

   Filter client-side: keep only books where `ofertas` array is empty.

   The environment variables `NEXT_PUBLIC_SUPABASE_URL` and
   `NEXT_PUBLIC_SUPABASE_ANON_KEY` are available in `.env.local`
   at the project root. Read that file to obtain the values.

3. **Filter known failures** — skip any book whose `slug` appears
   in `memory.failed_books`.

4. If the resulting `book_list` is empty after filtering:
   Inform the user ("Nenhum livro encontrado sem oferta.") and stop.

**book_list item schema (internal):**

```json
{
  "supabase_id": "uuid",
  "slug": "titulo-do-livro",
  "titulo": "Título do Livro",
  "autor": "Nome do Autor",
  "isbn": "9788500000000"
}
```

`isbn` is optional. All other fields are required.

Process at most `X` books from `book_list` in the order returned.

---

## Processing Steps (per book)

For each book in `book_list` (up to `X` books):

### Step 1 — Build search queries

Amazon BR queries (in order of preference):
1. `"{titulo}" "{autor}" livro site:amazon.com.br`
2. `{isbn} site:amazon.com.br` (only if isbn is available)

Mercado Livre queries (in order of preference):
1. `"{titulo}" "{autor}" livro site:mercadolivre.com.br`
2. `{isbn} site:mercadolivre.com.br` (only if isbn is available)

### Step 2 — Search

For each marketplace:

1. Run WebSearch with the primary query.
2. Collect up to 3 candidate URLs from results.
3. Filter out URLs that are clearly search/listing pages:
   - amazon.com.br/s?
   - lista.mercadolivre.com.br/
   - mercadolivre.com.br/ofertas
   - Any URL containing `/search`, `/category`, `?q=`

### Step 3 — Validate

For each candidate URL (in order):

1. Run WebFetch on the URL.
2. Check page content for:
   - ISBN match (if available) → confidence `high` if title also present
   - Exact title match (case-insensitive) AND author name → confidence `medium`
   - Approximate title match (≥ 80% of significant words) → confidence `low`
3. If validation passes: record the offer, stop checking further candidates
   for this marketplace.
4. If all candidates fail: record `not_found` for this marketplace.

### Step 4 — Build book result

Assemble the result object for this book:

```json
{
  "supabase_id": "...",
  "slug": "...",
  "titulo": "...",
  "ofertas": [...],
  "status": "found|partial|not_found"
}
```

Status rules:
- Both marketplaces found → `"found"`
- One marketplace found → `"partial"`
- Neither found → `"not_found"`

---

## Output File

Write the final result to:

```
scripts/data/offer_list.json
```

If the file already exists, overwrite it.

---

## Output Schema (IMMUTABLE)

```json
{
  "meta": {
    "total_livros": 0,
    "total_ofertas": 0,
    "gerado_em": "2026-01-01T00:00:00Z",
    "marketplaces": ["amazon", "mercadolivre"]
  },
  "livros": [
    {
      "supabase_id": "uuid",
      "slug": "titulo-do-livro",
      "titulo": "Título",
      "ofertas": [
        {
          "marketplace": "amazon",
          "url": "https://www.amazon.com.br/...",
          "confianca": "high",
          "needs_review": false
        },
        {
          "marketplace": "mercadolivre",
          "url": "https://www.mercadolivre.com.br/...",
          "confianca": "medium",
          "needs_review": false
        }
      ],
      "status": "found"
    }
  ]
}
```

Rules:
- JSON only — no markdown, no comments
- `meta.total_livros`: count of processed book entries
- `meta.total_ofertas`: count of valid offers recorded (sum of `ofertas` arrays)
- `meta.gerado_em`: ISO 8601 UTC timestamp of generation
- Keys MUST match character-by-character; no translation, no modification

---

## Post-Execution Memory Update

After writing `offer_list.json`:

1. Append to `memory.search_patterns`: any query pattern that
   consistently found valid results.
2. Append to `memory.failed_books`: slugs of books with
   `status: "not_found"`.
3. Append to `memory.marketplace_notes`: any structural patterns
   observed on marketplace pages (e.g. URL patterns, page structure changes).

Write updated memory back to `agents/offer_finder/memory.md`.

---

## Output Contract

The task is complete when:

1. `scripts/data/offer_list.json` exists and is valid JSON.
2. Every entry in `livros` has `supabase_id`, `slug`, `titulo`, `ofertas`, and `status`.
3. Every offer in `ofertas` has `marketplace`, `url`, `confianca`, and `needs_review`.
4. No offer URL is a search page or fabricated URL.
5. `agents/offer_finder/memory.md` has been updated.

---

## Operational Principle

search → fetch → validate → record → update memory
