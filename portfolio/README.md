# RESOLVE — Engineering Portfolio

RESOLVE is an intelligent exception-management platform for invoice operations. It combines
deterministic financial controls with evidence-grounded AI investigation and human approval, and it
runs as a verified Docker deployment with HTTPS, automation, observability and backup/restore.

**This portfolio is the story of a working system, not a mock-up.** Every screenshot comes from the
running deployment (`https://192.168.1.10:8180`), and every quality claim is backed by an executed
test run recorded in the repository.

## Read in this order

| Document | What it answers |
| --- | --- |
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | The problem, the users, the outcome, and what is verified |
| [TECHNICAL_ARCHITECTURE.md](TECHNICAL_ARCHITECTURE.md) | How the system is built, with nine Mermaid diagrams |
| [ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md) | The nine diagrams collected for quick viewing |
| [SYSTEM_FEATURES.md](SYSTEM_FEATURES.md) | What the product actually does, by module |
| [TECH_STACK.md](TECH_STACK.md) | Every technology and why it was chosen |
| [SECURITY_DESIGN.md](SECURITY_DESIGN.md) | AuthN/AuthZ, tenancy, approvals, secrets, network |
| [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) | Prompting, retrieval, evidence validation, failure modes |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | Schema, relationships, decimal money, pgvector |
| [TESTING_AND_QUALITY.md](TESTING_AND_QUALITY.md) | Test pyramid, 26-case acceptance suite, defect found & fixed |
| [DEPLOYMENT_OVERVIEW.md](DEPLOYMENT_OVERVIEW.md) | Compose topology, TLS, operations, backup/restore |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | Honest production gaps and external blockers |
| [DEMO_SCRIPT.md](DEMO_SCRIPT.md) | A 5–10 minute walkthrough for an interview |
| [DEMO_SCENARIOS.md](DEMO_SCENARIOS.md) | Three deeper scenarios with expected observations |
| [INTERVIEW_QA.md](INTERVIEW_QA.md) | 20 likely questions with answers grounded in this system |
| [qa/UX_REPORT.md](qa/UX_REPORT.md) | Responsive and console-error results for the live UI |
| [screenshots/](screenshots/) | Captured from the running product (no fabricated UI) |

## At a glance

- **Backend:** FastAPI, SQLAlchemy 2, PostgreSQL 16 + pgvector, Redis, Celery
- **Frontend:** React 19, TypeScript, Vite, TanStack Query, Tailwind-style design system
- **AI:** local Ollama (`qwen2.5:7b-instruct` + `bge-m3`), 1024-dim embeddings, hybrid retrieval
- **Documents:** PyMuPDF, python-docx, openpyxl, Tesseract OCR (Thai + English)
- **Automation:** n8n 2.48 with HMAC-signed events and Redis-backed idempotency
- **Ops:** Docker Compose, nginx TLS, Prometheus, Alertmanager, Grafana, Mailpit
- **Quality:** 137 backend tests, 10 Playwright E2E, 26 financial/security acceptance cases,
  16 security checks, 28-step live workflow

## The one-paragraph pitch

Finance teams lose days to invoice exceptions that arrive as unstructured documents, cross three
systems, and require a person to prove what happened. RESOLVE detects exceptions deterministically,
investigates them with an LLM whose every claim must cite a real organization-scoped record, and
resolves them through an approval policy that the requester cannot bypass. The result is faster
resolution with a defensible audit trail — and the AI is never allowed to approve or execute money.
