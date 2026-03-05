# Fact Extractor — Rules

## R1 — Source Restriction

Only descricao_base is allowed as semantic source.

Titulo and autor are NOT narrative sources.

---

## R2 — No Inference

The agent MUST NOT:

- infer themes not explicitly stated
- assume character relationships
- assume historical period
- assume narrative arc

If uncertain → leave field empty.

---

## R3 — Structured Output Only

Output MUST be valid JSON.

No prose allowed.

---

## R4 — Field Constraints

ambientacao:
  - explicit setting references only

contexto_social:
  - explicit social conditions only

conflito_central:
  - only if clearly described

personagens_mencionados:
  - only names explicitly written

temas_explicitos:
  - only themes directly stated

---

## R5 — Determinism

Equivalent descricao_base MUST produce equivalent JSON.