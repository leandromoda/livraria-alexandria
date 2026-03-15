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
- "tema_central"
- "abordagem"
- "conceitos_chave"
- "publico_alvo"
- "proposta_valor"

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

tema_central:
  - main subject, topic, or narrative thread
  - explicit references only
  - empty string if none

abordagem:
  - how the book treats the subject
  - explicit methodology, tone, or style only
  - empty string if none

conceitos_chave:
  - concepts, terms, or ideas directly stated
  - empty array if none

publico_alvo:
  - target audience only if explicitly described
  - empty string if none

proposta_valor:
  - what the reader gains, only if explicitly stated
  - empty string if none

---

## Extraction Examples

### tema_central

descricao_base fragment:
"Este livro explora as estratégias de marketing usadas por empresas modernas."

CORRECT:
"tema_central": "estratégias de marketing em empresas modernas"

INCORRECT:
"tema_central": ""   <- the subject is explicitly stated; leaving it empty is WRONG

---

### abordagem

descricao_base fragment:
"A obra apresenta casos reais e ferramentas práticas para aplicação imediata."

CORRECT:
"abordagem": "casos reais e ferramentas práticas"

INCORRECT:
"abordagem": ""   <- the approach is explicitly stated; leaving it empty is WRONG

---

### conceitos_chave

descricao_base fragment:
"O livro aborda branding, posicionamento e comportamento do consumidor."

CORRECT:
"conceitos_chave": ["branding", "posicionamento", "comportamento do consumidor"]

INCORRECT:
"conceitos_chave": []   <- the concepts are directly stated; leaving it empty is WRONG

---

### publico_alvo

descricao_base fragment:
"Indicado para profissionais de marketing e empreendedores."

CORRECT:
"publico_alvo": "profissionais de marketing e empreendedores"

INCORRECT:
"publico_alvo": ""   <- the audience is explicitly stated; leaving it empty is WRONG

---

### proposta_valor

descricao_base fragment:
"O leitor aprenderá a construir campanhas eficazes com baixo orçamento."

CORRECT:
"proposta_valor": "construir campanhas eficazes com baixo orçamento"

INCORRECT:
"proposta_valor": ""   <- the value is explicitly stated; leaving it empty is WRONG

---

## Extraction Principle

If a fact is written in descricao_base, it MUST be extracted.
An empty field is only valid when the information is truly absent.
Empty fields caused by omission are extraction failures.

---

## Output Format (STRICT)

Return EXACTLY:

{
  "tema_central": "",
  "abordagem": "",
  "conceitos_chave": [],
  "publico_alvo": "",
  "proposta_valor": ""
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
