# Technical architecture

RESOLVE is a modular monolith on the backend, a single-page application on the frontend, and a small
set of background workers and integration services around them. The architecture is intentionally
boring where correctness matters (money, permissions, approvals) and deliberately careful where AI
touches the system.

## 1. High-level system architecture

```mermaid
flowchart TB
  subgraph Client
    B["Browser<br/>React SPA + TypeScript"]
  end

  subgraph Edge["Edge (only LAN port)"]
    N["nginx<br/>TLS 1.2/1.3 · HSTS · SPA · /api proxy"]
  end

  subgraph App["Application tier (Docker network)"]
    API["FastAPI API<br/>REST · JWT · RBAC · validation"]
    W["Celery worker<br/>OCR · extraction · AI · execution"]
    BEAT["Celery beat<br/>outbox · expiry · notifications"]
  end

  subgraph Data["Data tier"]
    PG[("PostgreSQL 16<br/>+ pgvector 0.8")]
    RD[("Redis 7<br/>broker · cache · idempotency")]
    S3[("SeaweedFS S3<br/>documents")]
  end

  subgraph External["Local services"]
    OL["Ollama<br/>qwen2.5:7b + bge-m3"]
    MAIL["Mailpit SMTP"]
    N8N["n8n 2.48<br/>workflows A–E"]
  end

  subgraph Obs["Observability"]
    PR["Prometheus"]
    AM["Alertmanager"]
    GF["Grafana"]
    EX["Exporters<br/>pg · redis · nginx · celery · node · blackbox"]
  end

  B -->|HTTPS 8180| N
  N -->|/api| API
  API --> PG
  API --> RD
  API --> S3
  API -->|enqueue| RD
  BEAT --> RD
  W --> RD
  W --> PG
  W --> S3
  W -->|OpenAI-compatible| OL
  API -->|SMTP| MAIL
  API -->|signed webhook| N8N
  N8N -->|read-only API| API
  PR --> EX
  PR --> API
  PR --> AM
  AM --> MAIL
  GF --> PR
```

Only nginx is reachable from the LAN. PostgreSQL, Redis, object storage, n8n, monitoring and Mailpit
are bound to loopback or exist only on the Docker network.

## 2. Backend architecture

```mermaid
flowchart LR
  subgraph API["API layer"]
    R["Routers<br/>auth · users · vendors · POs<br/>invoices · documents · exceptions<br/>cases · investigations · resolutions<br/>approvals · analytics · audit · integrations"]
    AS["Analytics" ]
    INT["Internal automation<br/>/internal/automation/claims"]
    MET["/metrics"]
  end

  subgraph Core["Cross-cutting core"]
    SEC["security<br/>Argon2 · JWT · tokens"]
    DEP["dependencies<br/>principal · permissions"]
    ERR["error envelope"]
    RL["rate limiting"]
    CTX["request/correlation ids"]
  end

  subgraph Domain["Domain and services"]
    INV["invoices service<br/>decimal validation"]
    RULES["exception engine<br/>10 versioned rules"]
    DOC["documents service<br/>parse · OCR · extract · index"]
    CASE["cases service<br/>SLA · transitions · timeline"]
    AI["investigation service<br/>prompt · retrieve · validate"]
    RES["resolutions service<br/>policy · execute · idempotency"]
    APP["approvals service<br/>atomic decisions"]
    AUD["audit + outbox"]
  end

  subgraph Infra["Infrastructure"]
    DB["SQLAlchemy 2 / PostgreSQL"]
    CEL["Celery tasks"]
    ST["storage abstraction<br/>S3 or local"]
    LLM["AI provider abstraction<br/>Ollama/OpenAI/stub"]
  end

  R --> SEC --> DEP --> Domain
  R --> ERR
  R --> RL
  R --> CTX
  Domain --> Infra
  Domain --> AUD
  AUD --> DB
  Domain --> DB
  Domain --> CEL
  DOC --> ST
  AI --> LLM
```

Layering rules used in the codebase:

- Routers own HTTP concerns only; business logic lives in `modules/*/service.py`.
- Every query is scoped by `org_id`; permission checks are dependency-injected.
- Services return domain objects; Pydantic schemas shape the wire format.
- Background work is always enqueued after commit (transactional outbox pattern).
- Domain events are written in the same transaction as the business change and fanned out later, so a
  webhook failure never rolls back a financial decision.

## 3. Database relationships (core)

```mermaid
erDiagram
  ORGANIZATION ||--o{ MEMBERSHIP : has
  USER ||--o{ MEMBERSHIP : joins
  ROLE ||--o{ MEMBERSHIP : grants
  ROLE ||--o{ ROLE_PERMISSION : includes
  PERMISSION ||--o{ ROLE_PERMISSION : in

  ORGANIZATION ||--o{ VENDOR : owns
  VENDOR ||--o{ PURCHASE_ORDER : receives
  PURCHASE_ORDER ||--o{ PO_ITEM : contains
  ORGANIZATION ||--o{ INVOICE : owns
  VENDOR ||--o{ INVOICE : issues
  PURCHASE_ORDER ||--o{ INVOICE : matches
  INVOICE ||--o{ INVOICE_ITEM : contains
  INVOICE ||--o{ EXCEPTION : raises
  INVOICE ||--o{ VALIDATION_CHECK : checked

  DOCUMENT ||--o{ DOCUMENT_PAGE : has
  DOCUMENT ||--o{ DOCUMENT_VERSION : versions
  DOCUMENT ||--o{ DOCUMENT_CHUNK : chunks
  DOCUMENT ||--o{ EXTRACTION : extracts
  EXTRACTION ||--o{ EXTRACTED_FIELD : fields
  INVOICE ||--o| DOCUMENT : sourced_from

  EXCEPTION }o--o{ CASE : grouped_into
  CASE ||--o{ CASE_ACTIVITY : timeline
  CASE ||--o{ CASE_COMMENT : comments
  CASE ||--o{ INVESTIGATION : investigated
  INVESTIGATION ||--o{ INVESTIGATION_EVIDENCE : cites
  CASE ||--o{ RESOLUTION : proposes
  RESOLUTION ||--o| APPROVAL_REQUEST : requires
  APPROVAL_REQUEST ||--o{ APPROVAL_DECISION : records
  RESOLUTION ||--o{ RESOLUTION_EXECUTION : attempts

  ORGANIZATION ||--o{ AUDIT_LOG : records
  ORGANIZATION ||--o{ DOMAIN_EVENT : emits
  DOMAIN_EVENT ||--o{ WEBHOOK_EVENT : delivered_as
  INTEGRATION ||--o{ WEBHOOK_EVENT : routes
  INTEGRATION ||--o{ WORKFLOW_EXECUTION : triggers
```

Money is stored as `NUMERIC(18,4)` and handled with `Decimal` in Python (quantized to cents at the
boundary). Embeddings are `vector(1024)` with an HNSW index. Audit rows and domain events are
append-only by policy.

## 4. AI investigation pipeline

```mermaid
sequenceDiagram
  participant U as Investigator
  participant API as API
  participant W as Celery worker
  participant DB as PostgreSQL
  participant R as Retrieval
  participant L as Ollama
  participant V as Evidence validator

  U->>API: POST /cases/{id}/investigations
  API->>DB: create investigation (QUEUED)
  API->>W: enqueue run_investigation
  W->>DB: load case, exceptions, invoice, PO, vendor
  W->>R: hybrid search (keyword + cosine)
  R-->>W: top-k chunks (org-scoped) + similar cases
  W->>L: structured prompt + retrieved context
  L-->>W: summary, root cause, hypotheses, citations, proposals
  W->>V: validate every citation
  V->>DB: resolve document/page/chunk/case ids
  V-->>W: keep valid, flag invalid
  W->>DB: persist investigation + evidence + usage
  W->>DB: emit investigation.completed audit/event
  U->>API: GET /investigations/{id}
  API-->>U: status, evidence with is_validated, proposals
```

Safety properties:

- The prompt includes only records the requester may read and of the same organization.
- The model returns a strict JSON schema; malformed output is retried then failed.
- Citations that do not resolve to real rows are marked invalid; they are never shown as proof.
- The model cannot call tools, execute actions or write to the database.
- Token, cost and latency are persisted for every run.

## 5. Document processing pipeline

```mermaid
flowchart LR
  A["Upload<br/>MIME + magic + size + SHA-256"] --> B{"Duplicate?"}
  B -->|yes| B1["409 duplicate_document<br/>return existing id"]
  B -->|no| C["Store bytes in S3<br/>key = org/uuid/version/file"]
  C --> D["Document row (QUEUED)"]
  D --> E["Celery process_document"]
  E --> F["Download + parse<br/>PDF/DOCX/XLSX/CSV/TXT"]
  F --> G{"Text layer?"}
  G -->|no| H["Render page → Tesseract<br/>eng+tha"]
  G -->|yes| I["Extract text"]
  H --> I
  I --> J["Deterministic invoice parser<br/>labels · dates · amounts · tax ids"]
  J --> K{"Required fields?"}
  K -->|missing| L["Optional LLM fallback<br/>quote-validated"]
  K -->|complete| M["Arithmetic validation"]
  L --> M
  M --> N["Extraction + fields + confidence"]
  N --> O["Chunk + embed (bge-m3, 1024-d)"]
  O --> P["pgvector HNSW + knowledge search"]
  N --> Q["requires_review if low confidence / missing / arithmetic issue"]
  F -->|failure| X["Document FAILED<br/>redacted error + document.failed event"]
```

A corrupt file fails safely and can be reprocessed later; the failure emits a domain event that n8n
turns into an operator notification.

## 6. Exception to resolution workflow

```mermaid
stateDiagram-v2
  [*] --> Detected
  Detected --> Open: exception record
  Open --> Acknowledged: triage
  Open --> Linked: grouped into case
  Acknowledged --> Linked
  Linked --> Investigating: case assigned + AI run

  state Case {
    [*] --> OPEN
    OPEN --> INVESTIGATING
    INVESTIGATING --> AWAITING_INFORMATION
    INVESTIGATING --> AWAITING_APPROVAL: resolution proposed
    AWAITING_APPROVAL --> RESOLUTION_IN_PROGRESS: approved
    AWAITING_APPROVAL --> INVESTIGATING: rejected
    RESOLUTION_IN_PROGRESS --> RESOLVED: executed + resolved
    RESOLVED --> CLOSED
    RESOLVED --> REOPENED
  }

  AWAITING_APPROVAL --> Approved: authorized approver
  AWAITING_APPROVAL --> Rejected: reason required
  Approved --> Executed: idempotent execution
  Executed --> Audited
  Audited --> [*]
```

The requester cannot decide their own approval. Approval and execution are separate permissions.
A failed execution is persisted with its error and can be retried without duplicating the side effect.

## 7. Authentication and authorization flow

```mermaid
sequenceDiagram
  participant B as Browser
  participant N as nginx
  participant API as FastAPI
  participant DB as PostgreSQL

  B->>N: POST /api/v1/auth/login (email, password, org)
  N->>API: proxy
  API->>DB: load user + memberships
  API->>API: Argon2 verify (rate-limited 20/min/IP)
  API->>DB: create refresh token (hashed, rotated)
  API-->>B: access JWT (30 min) + refresh cookie (Secure/HttpOnly/Lax)
  B->>N: API call with Bearer + X-Organization-Id
  N->>API: proxy
  API->>API: verify JWT, load membership, check permission
  API-->>B: 200 or 403/404 scoped to the org
  B->>N: POST /auth/refresh (cookie only)
  N->>API: proxy
  API->>DB: validate + rotate refresh token, revoke previous
  API-->>B: new access token + rotated cookie
```

Refresh-token reuse is detected and revokes the session family. Logout revokes the session.
Password change signs out other sessions. Every request carries a correlation id used in logs and
error envelopes.

## 8. Deployment architecture

```mermaid
flowchart TB
  subgraph Windows["Windows 10 workstation"]
    subgraph WSL["Docker Desktop / WSL2"]
      subgraph Compose["Compose project resolve"]
        WEB["web :443 → host 8180"]
        API["api :8000 (127.0.0.1:8100)"]
        WRK["worker"]
        BEAT["beat"]
        PG["postgres (127.0.0.1:5433)"]
        RD["redis (127.0.0.1:6380)"]
        S3["seaweedfs (127.0.0.1:9100/9101)"]
        N8N["n8n (127.0.0.1:5679)"]
        MP["mailpit (127.0.0.1:8125)"]
        PR["prometheus (127.0.0.1:9190)"]
        AM["alertmanager (127.0.0.1:9193)"]
        GF["grafana (127.0.0.1:3101)"]
        EXP["exporters (internal)"]
      end
    end
    OLL["Ollama on host :11434"]
    FW["Firewall: TCP 8180<br/>Private + LocalSubnet only"]
    TASK["Scheduled tasks<br/>Docker watchdog · daily backup"]
    NATIVE["Native services<br/>rollback, 127.0.0.1:8090"]
  end
  LAN["LAN clients<br/>Windows / macOS"] -->|HTTPS 8180| FW --> WEB
  WRK -->|host.docker.internal| OLL
```

## 9. Backup and restore flow

```mermaid
flowchart LR
  A["scripts/backup-resolve.ps1<br/>or RESOLVE-Daily-Backup 02:30"] --> B["pg_dump -Fc"]
  A --> C["s3_sync download<br/>bucket → documents/"]
  B --> D["database.dump"]
  C --> E["documents mirror"]
  D --> F["manifest.json<br/>row counts · SHA-256 · bucket"]
  E --> F
  F --> G["backups/compose-<timestamp>"]
  G --> H["Prometheus metric<br/>last success timestamp"]
  G --> I["restore-resolve.ps1<br/>NEW database + bucket"]
  I --> J["verify counts · vectors · HNSW · SHA-256"]
  J --> K{"accept?"}
  K -->|yes| L["switch DATABASE_URL / S3_BUCKET"]
  K -->|no| M["discard isolated target<br/>live data untouched"]
```

Restores always go to a new database and bucket by default. The live database is never overwritten
during verification.

## 10. Architectural decisions worth defending

| Decision | Why |
| --- | --- |
| Modular monolith, not microservices | One team, one transaction boundary, simpler correctness for money and approvals |
| Postgres for relational + vectors | One operational dependency instead of two; HNSW is fast at this scale |
| Deterministic rules before AI | Auditable, cheap, and reproducible; AI only explains and recommends |
| Transactional outbox for events | Webhook/n8n failures cannot roll back financial changes |
| Separate approval object | Policy, expiry, assignment, self-approval and audit are first-class |
| Atomic claim for approvals | Prevents double decisions under concurrency (verified by test) |
| Loopback-only management plane | A single HTTPS entry point is a smaller attack surface |
| Local-first AI | No data leaves the machine; provider abstraction allows OpenAI-compatible endpoints |
