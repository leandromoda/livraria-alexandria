# Task: build_abstract_structure

## Objective

Convert factual extraction JSON into a structured conceptual representation.

This is NOT a narrative generation step.

---

## Input

The task receives:

{
  "ambientacao": "",
  "contexto_social": "",
  "conflito_central": "",
  "personagens_mencionados": [],
  "temas_explicitos": []
}

---

## Transformation

Perform deterministic mapping.

ambientacao → contexto

conflito_central → situacao_central

temas_explicitos → temas

contexto_social → escopo_narrativo

---

## Output Schema

The output MUST be valid JSON.

Required format:

{
  "contexto": "",
  "situacao_central": "",
  "temas": [],
  "escopo_narrativo": ""
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
  "escopo_narrativo": ""
}

---

## Determinism

Equivalent inputs MUST produce equivalent outputs.