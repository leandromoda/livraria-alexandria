# Task: build_abstract_structure

## Objective

Convert factual extraction JSON into a structured conceptual representation.

This is NOT a narrative generation step.

---

## Input

The task receives fact_extractor output:

{
  "tema_central": "",
  "abordagem": "",
  "conceitos_chave": [],
  "publico_alvo": "",
  "proposta_valor": "",
  "personagens": [],
  "ambientacao": "",
  "conflito_central": ""
}

---

## Transformation

Perform deterministic mapping (fiction fields take priority over non-fiction fields).

ambientacao OR tema_central → contexto

conflito_central OR abordagem → situacao_central

conceitos_chave → temas

proposta_valor OR publico_alvo → escopo_narrativo (when available)

personagens → personagens (pass through)

---

## Output Schema

The output MUST be valid JSON.

Required format:

{
  "contexto": "",
  "situacao_central": "",
  "temas": [],
  "escopo_narrativo": "",
  "personagens": []
}

Rules:

• No additional fields
• No commentary
• No explanations
• No markdown

---

## Failure Handling

If input JSON is malformed:

Return:

{
  "contexto": "",
  "situacao_central": "",
  "temas": [],
  "escopo_narrativo": "",
  "personagens": []
}

---

## Determinism

Equivalent inputs MUST produce equivalent outputs.
