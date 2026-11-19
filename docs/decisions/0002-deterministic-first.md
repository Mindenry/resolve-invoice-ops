# ADR 0002 — Deterministic first, AI bounded

- **Status:** accepted
- **Date:** 2026-02-14

## Context

Invoice exceptions involve money, tax, permissions and legal risk. LLMs are useful for language and
context but unreliable for exact arithmetic, policy or execution.

## Decision

All calculations, duplicate checks, tolerance comparisons, state transitions, permissions, approval
policy and execution are deterministic. AI is limited to extraction fallback, investigation summaries,
root-cause hypotheses, recommendations and evaluation. AI output is schema-validated, citations are
checked against real records, and no tools are exposed.

## Consequences

- Model failure is visible and never replaced with canned answers.
- Prompt injection cannot change policy or execute actions.
- Confidence is explicitly heuristic.
- Quality is measured in the evaluation lab rather than assumed.
