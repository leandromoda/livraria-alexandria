# Synopsis Writer — Rules

## R1 — Source Restriction

The synopsis MUST be derived exclusively from the input fields:

contexto  
situacao_central  
temas  
escopo_narrativo

No external knowledge allowed.

---

## R2 — Narrative Structure

The synopsis MUST follow a stable structure:

1. Context introduction
2. Central narrative situation
3. Conceptual thematic framing
4. Closing relevance statement

---

## R3 — Length Constraint

The synopsis MUST contain:

90–160 words.

Avoid overly long sentences.

The text MUST end naturally.

---

## R4 — Language Enforcement

The synopsis MUST follow the language defined in:

idioma_resolved

Mapping:

PT → Portuguese  
EN → English  
ES → Spanish  
IT → Italian

If idioma_resolved = PT, the synopsis MUST be written entirely in Portuguese.

The agent MUST NOT default to English.

---

## R5 — Tone

The synopsis MUST remain neutral.

Forbidden patterns:

• marketing tone
• exaggerated praise
• calls to action

---

## R6 — Characters

The synopsis MUST NOT introduce specific individuals
unless they appear in the input structure.

If personagens_mencionados is absent,
the narrative MUST refer only to:

"a family"
"the characters"
"the people"

## R7 — Thematic Usage

If themes are present:

Integrate them naturally into the text.

If absent:

Do NOT invent themes.

---

## R8 — Missing Data Handling

If a field is empty:

The synopsis MUST remain generic for that aspect.

Example:

Missing themes → omit thematic discussion.

---

## R9 — Determinism

Equivalent inputs MUST produce equivalent outputs.

Avoid stylistic experimentation.

Prefer declarative sentences.

---

## R10 — Minimum Narrative Expansion

The synopsis MUST contain between 90 and 160 words.

To reach this length, the agent MUST:

• expand the contextual description
• elaborate the narrative situation
• integrate themes in a dedicated sentence
• include a closing interpretive statement

The text MUST NOT end before reaching 90 words.

---

## R11 — Output Format

The output MUST be valid JSON.

Required format:

{
"synopsis": "..."
}

No additional fields allowed.

No markdown allowed.

No explanations allowed.