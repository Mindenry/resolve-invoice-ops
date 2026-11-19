# Tech stack and rationale

Versions are the ones actually running in the verified deployment (checked 2026-11-19).

## Backend

| Technology | Version | Role | Why |
| --- | --- | --- | --- |
| Python | 3.12 | runtime | modern typing, performance, mature ecosystem |
| FastAPI | ≥0.115 | HTTP API | typed schemas, dependency injection, OpenAPI |
| Pydantic | 2.9+ | validation | strict request/response models, settings via env |
| SQLAlchemy | 2.0 | ORM | typed models, explicit transactions, portability |
| Alembic | 1.13+ | migrations | versioned schema changes, no auto-DDL in production |
| PostgreSQL | 16.16 | primary store | ACID, NUMERIC money, JSONB, extensions |
| pgvector | 0.8.7 | vector store | HNSW similarity search next to relational data |
| Redis | 7 | broker/cache/idempotency | simple, fast, one dependency for three needs |
| Celery | 5.4 | background jobs | retries, scheduling, separate worker lifecycle |
| Argon2-cffi | 23.1+ | password hashing | memory-hard, recommended default |
| PyJWT | 2.9+ | tokens | small, explicit JWT implementation |
| httpx | 0.27+ | outbound HTTP | sync/async, test-friendly |
| slowapi | 0.1.9+ | rate limiting | route-level limits with a simple key function |
| structlog | 24.4+ | logging | structured events, request context binding |
| prometheus-client | 0.21+ | metrics | standard exposition format |
| boto3 | 1.35+ | S3 | path-style access to SeaweedFS or managed S3 |
| PyMuPDF | 1.24+ | PDF | text, page render, OCR input |
| python-docx / openpyxl | current | DOCX/XLSX | native parsing without external services |
| pytesseract + Tesseract | 5.4 | OCR | Thai + English, runs in the container |
| Pillow | 10.4+ | images | preprocessing, OCR input, test fixtures |
| reportlab | 4.2+ | PDF generation | synthetic acceptance documents |
| tenacity | 9.0+ | retries | bounded retry with backoff for AI/providers |

## Frontend

| Technology | Role | Why |
| --- | --- | --- |
| React 19 + TypeScript | SPA | component model, strict types across API contracts |
| Vite | build/dev | fast builds, simple production output |
| React Router | routing | 20+ routes with permission wrappers |
| TanStack Query | server state | caching, invalidation, retries, real loading/error states |
| Tailwind-style utility classes + CSS variables | design system | consistent tokens, light/dark themes, no runtime CSS-in-JS |
| Recharts (chart bundle) | analytics charts | declarative charts from real API data |
| Vitest + Testing Library | unit tests | fast component/utility tests |
| Playwright | E2E | real browser, real HTTPS, real backend |

## AI and retrieval

| Technology | Role | Why |
| --- | --- | --- |
| Ollama | local model runtime | no data leaves the machine; no fake API keys |
| qwen2.5:7b-instruct | investigation model | good structured output at 7B on a workstation |
| bge-m3 | embeddings | multilingual (Thai/English), 1024 dimensions |
| pgvector HNSW | vector index | low-latency approximate search inside PostgreSQL |
| Hybrid scoring | retrieval | keyword weight 0.45 + vector weight 0.55, configurable |
| Provider abstraction | portability | OpenAI-compatible endpoints supported without code changes |

## Automation, edge and operations

| Technology | Version | Role | Why |
| --- | --- | --- | --- |
| nginx | 1.27 | TLS + SPA + reverse proxy | one hardened entry point |
| mkcert | 1.4.4 | local CA | trusted HTTPS on LAN without a public domain |
| n8n | 2.48.6 | workflow automation | real integrations with HMAC and retries |
| Mailpit | 1.34 | local SMTP sink | safe email testing without external delivery |
| SeaweedFS | 4.54 | S3-compatible storage | MinIO is retired upstream; authenticated path-style S3 |
| Prometheus | 3.1.0 | metrics | pull model, PromQL, 15-day retention |
| Alertmanager | 0.28 | alert routing | grouping, inhibition, Mailpit delivery |
| Grafana | 13.3.1 | dashboards | provisioned from Git, four dashboards |
| Docker Desktop / Engine | 4.99 / 29.9.3 | container runtime | reproducible deployment on this workstation |
| Windows Task Scheduler | — | watchdog + daily backup | survives idle exits and schedules backups |

## Testing and tooling

| Tool | Role |
| --- | --- |
| pytest + pytest-cov | backend unit/integration tests |
| Ruff | lint and import/format checks |
| Playwright | E2E, screenshots, responsive checks |
| Vitest | frontend unit tests |
| TypeScript compiler | static type gate |
| Git | baseline, history, annotated release tag |

## Deliberate non-choices

- **No Kubernetes:** one workstation, one team; the operational cost is not justified.
- **No microservices:** money and approvals need one transaction boundary.
- **No external vector database:** pgvector keeps tenancy, joins and backups simple.
- **No client-side authorization:** permissions are enforced server-side; the UI only hides actions.
- **No LLM tool-calling:** the model never executes actions; proposals become typed records that a
  human must approve.
