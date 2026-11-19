# ADR 0005 — Async work with a local fallback

- **Status:** accepted
- **Date:** 2026-02-14

## Context

OCR, extraction, AI calls and evaluation must not run inside HTTP requests. Requiring Redis for every
local demo would make the project harder to evaluate.

## Decision

Persist every task as a `background_jobs` row. Dispatch to Celery when a broker is configured;
otherwise run on a bounded thread pool, or inline in tests. Task handlers are domain-idempotent.
Document processing claims the document atomically to prevent duplicate work.

## Consequences

- Job status, errors and retries are visible in all modes.
- The local runner is not durable across process restarts; Celery is required in production.
- Inline mode makes tests deterministic at the cost of running work in the request thread.
