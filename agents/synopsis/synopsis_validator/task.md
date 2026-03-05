# Synopsis Validator — Task Definition

## Task Name

validate_generated_synopsis

---

## Purpose

Evaluate a generated synopsis and determine whether it satisfies all publication constraints defined by the synopsis pipeline.

The task performs validation only.

No rewriting or content generation is allowed.

---

## Inputs

Runtime input provided by executor:

runtime:
synopsis
idioma_resolved

All fields are mandatory.

If any field is missing or empty:

TASK_ABORTED

---

## Preconditions

Execution allowed only when:

* synopsis length > 0
* idioma_resolved is a valid language code

Otherwise:

TASK_ABORTED

---

## Validation Steps

### Step 1 — Language Verification

Confirm that the synopsis is written entirely in:

language_locked = runtime.idioma_resolved

Checks:

* no mixed languages
* no untranslated fragments

If violation detected:

REWRITE_REQUIRED

---

### Step 2 — Length Constraint

The synopsis MUST contain:

90–160 words.

If outside range:

REWRITE_REQUIRED

---

### Step 3 — Structural Integrity

Verify:

* complete sentences
* coherent paragraph flow
* no abrupt ending
* no duplicated opening fragments

If structure invalid:

REWRITE_REQUIRED

---

### Step 4 — Editorial Neutrality

Reject if text contains:

* promotional tone
* exaggerated praise
* marketing language
* calls to action

If detected:

REWRITE_REQUIRED

---

### Step 5 — Meta Artifact Detection (CRITICAL)

The synopsis MUST NOT contain:

* `[SYSTEM]`
* `[PROCESS]`
* `[TASK]`
* markdown headings (`#`, `##`)
* prompt fragments
* instruction-like text
* JSON fragments inside prose

If any detected:

REWRITE_REQUIRED

---

### Step 6 — Output Purity

Ensure synopsis is plain prose:

* no markdown formatting
* no bullet lists
* no explanations
* no generation references

If violated:

REWRITE_REQUIRED

---

## Decision Rule

If ALL validations pass:

Return APPROVED.

Otherwise:

Return REWRITE_REQUIRED.

---

## Output Contract (STRICT)

The final response MUST be exactly one of:

{
"status": "APPROVED"
}

or

{
"status": "REWRITE_REQUIRED"
}

Rules:

* JSON only
* no additional keys
* no explanations
* no surrounding text

Any deviation is INVALID.

---

## Deterministic Constraints

The validator MUST:

* apply rules consistently
* avoid interpretation beyond checks
* produce identical decisions for identical inputs

---

## Failure Modes

### TASK_ABORTED

Triggered when:

* missing inputs
* invalid language code

---

### TASK_FAILED

Triggered when:

* output format cannot be validated
* internal validation cannot complete

---

## Executor Compatibility

Execution success occurs when:

* JSON is parseable
* "status" field exists
* value is APPROVED or REWRITE_REQUIRED

Executor uses decision for pipeline gating.

---

## Operational Principle

check → enforce → decide → return