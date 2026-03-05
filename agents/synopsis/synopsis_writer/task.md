# Task — Generate Book Synopsis

## Objective

Transform a structured abstract into a readable book synopsis.

This task performs narrative synthesis based strictly on structured input.

---

## Input

The task receives:

{
"contexto": "",
"situacao_central": "",
"temas": [],
"escopo_narrativo": ""
}

---

## Generation Process

The synopsis must integrate the input components in logical order.

Recommended flow:

contexto → situacao_central → escopo_narrativo → temas

Themes should appear naturally within the narrative.

---

## Output Requirements

The output MUST be valid JSON.

Format:

{
"synopsis": "..."
}

Rules:

• 90–160 words  
• neutral editorial tone  
• no markdown  
• no commentary  
• no additional fields  

---

## Failure Handling

If insufficient data exists:

Produce a general synopsis using available information.

Never invent plot elements.

---

## Determinism

Repeated executions with identical inputs must yield equivalent results.