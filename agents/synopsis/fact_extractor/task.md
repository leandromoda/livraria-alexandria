# Fact Extractor — Task

## Task Name

extract_structured_facts

---

## Inputs

runtime:
  descricao_base
  idioma_resolved

If descricao_base is null, empty, or whitespace-only:

TASK_ABORTED

---

## Schema Lock (IMMUTABLE)

You MUST return a JSON object with EXACTLY the following keys.

The keys are IDENTIFIERS.
They are NOT natural language.
They MUST NOT be translated.
They MUST NOT be modified.
They MUST NOT be reformatted.
They MUST NOT be renamed.
They MUST NOT contain accents.
They MUST match character-by-character.

Required keys (exact spelling):

- "ambientacao"
- "contexto_social"
- "conflito_central"
- "personagens_mencionados"
- "temas_explicitos"

No additional keys are allowed.
No missing keys are allowed.

---

## Processing Rules

Read descricao_base carefully.

Extract ONLY explicitly stated elements.

DO NOT:

- infer
- interpret
- summarize
- paraphrase
- translate field names
- add commentary
- explain decisions

If information is not explicitly present,
leave the field as empty string "" or empty array [].

---

## Field Constraints

ambientacao:
  - explicit setting references only
  - empty string if none

contexto_social:
  - explicit social conditions only
  - empty string if none

conflito_central:
  - explicit central conflict only
  - empty string if none

personagens_mencionados:
  - only names explicitly written
  - empty array if none

temas_explicitos:
  - only themes directly stated
  - empty array if none

---

## Output Format (STRICT)

Return EXACTLY:

{
  "ambientacao": "",
  "contexto_social": "",
  "conflito_central": "",
  "personagens_mencionados": [],
  "temas_explicitos": []
}

Rules:

- JSON only
- No markdown fences
- No comments
- No explanatory text
- No extra text before or after JSON
- No translated keys
- No modified keys

Any deviation is INVALID.