# ADR 0003 — Session token strategy

- **Status:** accepted
- **Date:** 2026-02-14

## Context

The SPA needs resilient sessions without exposing long-lived credentials to JavaScript or making
mutations CSRF-able.

## Decision

Keep the short-lived access token in memory. Store the refresh token in an httpOnly, SameSite=Lax
cookie scoped to `/api/v1/auth`, rotate on every use, store hashes only, and revoke the token family
on reuse. Mutating API calls use the bearer token, not the cookie.

## Consequences

- Reload triggers one refresh request (only when a session marker exists).
- XSS cannot read the refresh token; CSRF cannot trigger mutations because cookies are not accepted
  for authenticated endpoints.
- Cross-site frontends must use the same site or an explicit proxy.
