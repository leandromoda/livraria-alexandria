```md
# Synopsis Agent — Task Definition

## Task Name

generate_validated_synopsis

---

## Purpose

Produce a publishable book synopsis using a deterministic Markdown-oriented agent workflow.

The task orchestrates:

1. Context preparation  
2. Synopsis generation  
3. Editorial criticism  
4. Validation and final output

The task MUST produce either:

- an approved synopsis
- or a rewrite request

No intermediate states are allowed as final output.

---

## Inputs

Runtime receives:

livro:
  titulo
  autor
  descricao
  idioma
  cluster
  editorial_score

pipeline:
  semantic_core
  plan

All inputs are mandatory.

---

## Preconditions

The task MUST execute only if:

is_book == 1  
editorial_score >= 0  
status_slug == 1  
status_dedup == 1  

If any condition fails:

TASK_ABORTED

---

## Language Resolution

Language is resolved before generation.

runtime.idioma_resolved =
  livro.idioma
  OR pipeline.language_override
  OR PT

Language MUST remain locked for entire execution.

---

## Execution Workflow

### Phase 1 — Context Build

Construct generation context:

context:
  language_locked
  semantic_core
  plan
  metadata:
    titulo
    autor
    cluster

No external enrichment allowed.

---

### Phase 2 — Generation

Invoke generator using:

- identity.md
- rules.md
- workflow.md

Output:

draft.synopsis

Requirements:

- 90–160 words
- neutral tone
- structured narrative
- language locked

---

### Phase 3 — Critic Review

Send draft to critic module.

Input:

validated.synopsis = draft.synopsis

Critic evaluates:

- language compliance
- structure
- neutrality
- semantic fidelity
- readability

---

### Phase 4 — Decision Gate

If critic.status == APPROVED

→ proceed to finalization.

If critic.status == REWRITE_REQUIRED

→ restart generation phase.

Maximum retries:

max_attempts = 2

After limit:

TASK_FAILED

---

## Final Output

Approved result format:

task: generate_validated_synopsis
status: SUCCESS

output:
  synopsis: <text>
  language: <locked_language>
  validated: true

No explanations allowed.

---

## State Updates

On success:

status_synopsis = 1  
updated_at = now()

On failure:

status_synopsis = -1

---

## Deterministic Constraints

The task MUST:

- avoid creative drift
- avoid external knowledge
- follow workflow strictly
- produce stable outputs for equivalent inputs

Randomness is forbidden.

---

## Error Handling

### Abort Conditions

- missing metadata
- empty semantic_core
- invalid language code

Return:

TASK_ABORTED

---

### Failure Conditions

- critic fails twice
- synopsis cannot stabilize
- structural violations persist

Return:

TASK_FAILED

---

## Pipeline Output Enforcement (STRICT)

The final agent response MUST be a single valid JSON object.

Mandatory rules:

- Output MUST contain ONLY JSON.
- Output MUST NOT contain markdown.
- Output MUST NOT contain headings.
- Output MUST NOT contain explanations.
- Output MUST NOT contain additional sections.
- Output MUST NOT contain labels such as EXPLANATION, SYSTEM, NOTES, or COMMENTS.

The JSON structure MUST be exactly:

{
  "synopsis": "<final validated synopsis>"
}

No additional keys are allowed.

If any other text is produced, the result is INVALID and MUST be regenerated.

---

## Executor Compatibility (MANDATORY)

When execution succeeds, the critic output MUST contain the literal token:

APPROVED

This token is required for deterministic detection by the Markdown Executor.

The token MUST appear exactly as:

APPROVED
```