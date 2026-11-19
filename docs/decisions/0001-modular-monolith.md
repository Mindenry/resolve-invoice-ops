# ADR 0001 — Modular monolith

- **Status:** accepted
- **Date:** 2026-02-14

## Context

RESOLVE coordinates documents, invoices, rules, cases, AI investigations, approvals and audit in one
operational flow. Early scale is modest and the dominant risk is correctness, not throughput.

## Decision

Build a single FastAPI deployable organized as domain modules (`app/modules/<domain>`), each owning
models, schemas, services and routers. Cross-cutting behaviour lives in `app/services`; background
work in `app/workers`. No module imports another module's router.

## Consequences

- One transaction can cover detection + case grouping + audit.
- Authorization and organization isolation are implemented once.
- Extraction into services later is possible but not free; module boundaries and service interfaces
  must be respected.
