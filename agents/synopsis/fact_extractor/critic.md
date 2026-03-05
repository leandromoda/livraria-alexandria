# Fact Extractor — Critic

## Purpose

Validate structural and semantic fidelity of extracted facts.

---

## Validation Rules

1. Output MUST be valid JSON.
2. No prose allowed.
3. No field may contain invented content.
4. If a name appears that is not in descricao_base → REWRITE_REQUIRED.
5. If a theme is inferred but not explicit → REWRITE_REQUIRED.

---

## Output (STRICT)

If valid:

APPROVED

If invalid:

REWRITE_REQUIRED