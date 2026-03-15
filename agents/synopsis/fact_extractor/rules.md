# Fact Extractor — Rules

## R1 — Source Restriction

Only descricao_base is allowed as semantic source.

Titulo and autor are NOT narrative sources.

---

## R2 — No Inference

The agent MUST NOT:

- infer themes not explicitly stated
- assume audience not described
- assume approach or methodology
- assume value proposition

If uncertain → leave field empty.

---

## R3 — Structured Output Only

Output MUST be valid JSON.

No prose allowed.

---

## R4 — Field Constraints

tema_central:
  - the main subject, topic, or narrative thread
  - explicit references only

abordagem:
  - how the book treats the subject
  - explicit methodology, style, or angle only

conceitos_chave:
  - only concepts, terms, or ideas directly stated

publico_alvo:
  - only if explicitly described in descricao_base

proposta_valor:
  - what the reader gains, only if explicitly stated

---

## R5 — Determinism

Equivalent descricao_base MUST produce equivalent JSON.
