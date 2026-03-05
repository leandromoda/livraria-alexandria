# Abstract Structurer — Rules

## R1 — Source Restriction

The agent MUST use ONLY the fields present in the input JSON.

No external knowledge allowed.

---

## R2 — Structural Mapping

Map extracted facts into four conceptual blocks.

Mapping guidelines:

ambientacao → contexto

conflito_central → situacao_central

temas_explicitos → temas

contexto_social → escopo_narrativo (when available)

If a field is empty in the input, the mapped field MUST also be empty.

---

## R3 — No Creative Expansion

The agent MUST NOT:

• add narrative elements
• invent conflicts
• infer story arcs
• expand themes

This step is structural, not interpretive.

---

## R4 — Deterministic Output

The output MUST contain exactly these keys:

{
"contexto": "",
"situacao_central": "",
"temas": [],
"escopo_narrativo": ""
}

No additional keys allowed.

---

## R5 — Language Neutrality

The agent MUST preserve the language present in the input.

No translation allowed.

---

## R6 — Empty Field Policy

If no reliable mapping exists, the field MUST be empty.

Do NOT fabricate values.