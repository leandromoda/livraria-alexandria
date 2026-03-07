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
## Extraction Examples

### ambientacao

descricao_base fragment:
"A história se passa no sertão nordestino, marcado por longos períodos de seca."

CORRECT:
"ambientacao": "sertão nordestino, marcado por longos períodos de seca"

INCORRECT:
"ambientacao": ""   ← the setting is explicitly stated; leaving it empty is WRONG

---

### conflito_central

descricao_base fragment:
"O romance retrata a luta pela sobrevivência em um ambiente hostil."

CORRECT:
"conflito_central": "luta pela sobrevivência em ambiente hostil"

INCORRECT:
"conflito_central": ""   ← the conflict is explicitly stated; leaving it empty is WRONG

---

### contexto_social

descricao_base fragment:
"A narrativa acompanha suas dificuldades diante da pobreza e da escassez de recursos."

CORRECT:
"contexto_social": "dificuldades diante da pobreza e da escassez de recursos"

INCORRECT:
"contexto_social": ""   ← the social condition is explicitly stated; leaving it empty is WRONG

---

### personagens_mencionados

descricao_base fragment:
"Fabiano e sua família vivem no sertão nordestino."

CORRECT:
"personagens_mencionados": ["Fabiano"]

INCORRECT:
"personagens_mencionados": []   ← the name is explicitly written; leaving it empty is WRONG

---

### temas_explicitos

descricao_base fragment:
"O livro aborda a pobreza, a seca e a esperança de dias melhores."

CORRECT:
"temas_explicitos": ["pobreza", "seca", "esperança"]

INCORRECT:
"temas_explicitos": []   ← the themes are directly stated; leaving it empty is WRONG

---

## Extraction Principle

If a fact is written in descricao_base, it MUST be extracted.
An empty field is only valid when the information is truly absent.
Empty fields caused by omission are extraction failures.

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