# Offer Finder — Rules

## R1 — Target Books

Process only books that satisfy ALL conditions:

- `supabase_id` is filled (book is published)
- No active offer exists for that `supabase_id` in the output list
- The book has a valid `titulo` and `autor`

Books without `supabase_id` MUST be skipped.

---

## R2 — Supported Marketplaces

Mandatory search targets:

- **Amazon BR**: `amazon.com.br`
- **Mercado Livre**: `mercadolivre.com.br`

One offer per marketplace per book (maximum 2 offers per book).

---

## R3 — URL Validation

A URL is only valid when the fetched page contains AT LEAST ONE of:

- The book's ISBN (if available)
- The book's exact title (case-insensitive)
- The book's title AND author name together

URLs that point to search result pages, category pages,
or general listings are INVALID and MUST be discarded.

A valid URL MUST point to a specific product page.

---

## R4 — Confidence Levels

Assign confidence based on what matched on the product page:

| Evidence matched            | Confidence |
|-----------------------------|------------|
| ISBN + title                | `high`     |
| Title + author name         | `medium`   |
| Title only (approximate)    | `low`      |

If no match can be established: do NOT record the offer.

---

## R5 — Review Flag

Offers with `confianca: "low"` MUST have `needs_review: true`.

Offers with `confianca: "medium"` or `"high"` MUST have `needs_review: false`.

---

## R6 — Not Found Handling

If no valid offer is found for a marketplace after exhausting
the top 3 search results:

- Do NOT fabricate a URL
- Do NOT use a search page URL
- Record `status: "not_found"` for that book
- Leave `ofertas` array empty or with only found marketplaces

---

## R7 — Schema Lock

The output JSON keys are IMMUTABLE.

They MUST NOT be translated, renamed, or reformatted.

Keys: `meta`, `livros`, `supabase_id`, `slug`, `titulo`, `ofertas`,
`marketplace`, `url`, `confianca`, `needs_review`, `status`,
`total_livros`, `total_ofertas`, `gerado_em`, `marketplaces`.

---

## R8 — Multiple Offers Per Book

Each book entry may contain up to 2 offer objects in the `ofertas` array:
one per marketplace.

If only one marketplace yields a valid offer, record only that one.
`status` must reflect the result:

- `"found"` — at least one valid offer found
- `"partial"` — only one of the two marketplaces yielded a valid offer
- `"not_found"` — no valid offer found on any marketplace

---

## R9 — Determinism

Processing the same `book_list` with the same search results
MUST produce equivalent output.

Do not introduce random ordering or non-deterministic choices.
When multiple valid URLs exist for the same marketplace,
prefer the one with higher confidence, then the first in search order.

---

## R10 — Search Query Format

Use structured queries for each marketplace:

**Amazon BR:**
```
"{titulo}" "{autor}" livro site:amazon.com.br
```

**Mercado Livre:**
```
"{titulo}" "{autor}" livro site:mercadolivre.com.br
```

If ISBN is available, also try:
```
{isbn} site:amazon.com.br
{isbn} site:mercadolivre.com.br
```

Fetch and validate up to 3 candidate URLs per marketplace before
concluding `not_found`.
