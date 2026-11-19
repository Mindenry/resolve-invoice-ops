# Architecture diagrams

All diagrams use Mermaid and render on GitHub/GitLab. They reflect the implementation, not an
aspirational design.

## 1. High-level system architecture

```mermaid
flowchart TB
  B["Browser SPA"] -->|HTTPS 8180| N["nginx: TLS · SPA · /api"]
  N --> API["FastAPI API"]
  API --> PG[("PostgreSQL + pgvector")]
  API --> RD[("Redis")]
  API --> S3[("SeaweedFS S3")]
  API -->|enqueue| RD
  W["Celery worker"] --> PG
  W --> S3
  W -->|OpenAI-compatible| OL["Ollama"]
  BEAT["Celery beat"] --> RD
  API -->|SMTP| MP["Mailpit"]
  API -->|HMAC webhook| N8N["n8n A–E"]
  N8N -->|read-only| API
  PR["Prometheus"] --> API
  PR --> EX["Exporters"]
  PR --> AM["Alertmanager"]
  AM --> MP
  GF["Grafana"] --> PR
```

## 2. Backend architecture

```mermaid
flowchart LR
  R["Routers"] --> D["Dependencies<br/>JWT · permissions · tenancy"]
  D --> S["Domain services<br/>invoices · rules · documents · cases<br/>AI · resolutions · approvals"]
  S --> DB["SQLAlchemy → PostgreSQL"]
  S --> Q["Celery tasks"]
  S --> A["Audit + outbox"]
  S --> ST["Storage abstraction"]
  S --> LLM["AI provider abstraction"]
  C["Core<br/>errors · rate limit · request ids · security"] --- R
```

## 3. Database relationships

```mermaid
erDiagram
  ORGANIZATION ||--o{ INVOICE : owns
  ORGANIZATION ||--o{ CASE : owns
  ORGANIZATION ||--o{ DOCUMENT : owns
  VENDOR ||--o{ PURCHASE_ORDER : receives
  VENDOR ||--o{ INVOICE : issues
  PURCHASE_ORDER ||--o{ INVOICE : matched
  INVOICE ||--o{ INVOICE_ITEM : has
  INVOICE ||--o{ EXCEPTION : raises
  INVOICE ||--o| DOCUMENT : source
  DOCUMENT ||--o{ DOCUMENT_PAGE : pages
  DOCUMENT ||--o{ DOCUMENT_CHUNK : embeddings
  DOCUMENT ||--o{ EXTRACTION : extracts
  EXTRACTION ||--o{ EXTRACTED_FIELD : fields
  EXCEPTION }o--o{ CASE : grouped
  CASE ||--o{ INVESTIGATION : runs
  INVESTIGATION ||--o{ INVESTIGATION_EVIDENCE : cites
  CASE ||--o{ RESOLUTION : proposes
  RESOLUTION ||--o| APPROVAL_REQUEST : requires
  APPROVAL_REQUEST ||--o{ APPROVAL_DECISION : decides
  RESOLUTION ||--o{ RESOLUTION_EXECUTION : attempts
  ORGANIZATION ||--o{ AUDIT_LOG : records
  DOMAIN_EVENT ||--o{ WEBHOOK_EVENT : delivered
```

## 4. AI investigation pipeline

```mermaid
flowchart TD
  A["Case + exceptions + invoice + PO + vendor"] --> B["Hybrid retrieval<br/>keyword 0.45 + cosine 0.55 + similar cases"]
  B --> C["Prompt v2<br/>schema · rules · delimited context"]
  C --> D["Ollama qwen2.5:7b-instruct"]
  D --> E{"Schema valid?"}
  E -->|no| F["Retry, then fail honestly"]
  E -->|yes| G["Validate every citation<br/>org-scoped document/page/chunk/case"]
  G --> H{"All valid?"}
  H -->|no| I["Flag invalid · NEEDS_REVIEW"]
  H -->|yes| J["Persist evidence · usage · suggestions"]
  I --> J
  J --> K["Proposals — never executed by AI"]
```

## 5. Document processing pipeline

```mermaid
flowchart LR
  U["Upload"] --> V{"MIME · magic · size · SHA-256"}
  V -->|duplicate| V1["409 + existing id"]
  V -->|ok| S["Store in S3"]
  S --> Q["QUEUED"]
  Q --> P["Parse PDF/DOCX/XLSX/CSV/TXT"]
  P --> O{"Text layer?"}
  O -->|no| T["Tesseract eng+tha"]
  O -->|yes| X["Extract text"]
  T --> X
  X --> F["Deterministic field parser"]
  F --> L{"Required fields?"}
  L -->|missing| M["LLM fallback with quotes"]
  L -->|ok| AR["Arithmetic validation"]
  M --> AR
  AR --> E["Extraction + confidence"]
  E --> CH["Chunk + embed 1024-d"]
  CH --> HNSW["pgvector HNSW"]
  P -->|failure| FAIL["FAILED + document.failed event"]
```

## 6. Exception resolution workflow

```mermaid
stateDiagram-v2
  [*] --> Detected
  Detected --> Open
  Open --> Linked: grouped into case
  Linked --> Investigating
  Investigating --> AWAITING_APPROVAL: proposal
  AWAITING_APPROVAL --> Approved: non-requester approver
  AWAITING_APPROVAL --> Investigating: rejected
  Approved --> Executed: idempotent
  Executed --> Resolved
  Resolved --> Closed
  Resolved --> Reopened
  Closed --> [*]
```

## 7. Authentication and authorization

```mermaid
sequenceDiagram
  participant B as Browser
  participant N as nginx
  participant A as API
  participant D as DB
  B->>N: login (email, password, org)
  N->>A: proxy
  A->>D: user + memberships
  A->>A: Argon2 + rate limit
  A->>D: hashed refresh token
  A-->>B: access JWT + HttpOnly/Secure refresh cookie
  B->>N: API call (Bearer + X-Organization-Id)
  N->>A: proxy
  A->>A: verify JWT, permission, org scope
  A-->>B: 200 / 403 / 404
  B->>N: refresh (cookie)
  A->>D: rotate + reuse detection
  A-->>B: new access token + rotated cookie
```

## 8. Deployment architecture

```mermaid
flowchart TB
  LAN["LAN clients"] -->|TCP 8180 only| FW["Windows Firewall<br/>Private · LocalSubnet"]
  FW --> WEB["web (nginx TLS)"]
  subgraph Docker["Docker Compose (WSL2)"]
    WEB --> API["api"]
    API --> PG[("postgres")]
    API --> RD[("redis")]
    API --> S3[("seaweedfs")]
    WRK["worker"] --> PG
    BEAT["beat"] --> RD
    N8N["n8n (loopback)"]
    PR["prometheus (loopback)"]
    GF["grafana (loopback)"]
    MP["mailpit (loopback)"]
  end
  WRK -->|host.docker.internal| OLL["Ollama on host"]
  TASKS["Scheduled tasks<br/>watchdog · daily backup"] -.-> Docker
```

## 9. Backup and restore

```mermaid
flowchart LR
  A["Backup task / script"] --> B["pg_dump -Fc"]
  A --> C["S3 mirror"]
  B --> M["manifest.json<br/>counts · SHA-256"]
  C --> M
  M --> D["backups/compose-<stamp>"]
  D --> E["restore script"]
  E --> F["NEW database + NEW bucket"]
  F --> G["verify counts · vector 1024 · HNSW · SHA-256"]
  G --> H["switch DATABASE_URL/S3_BUCKET after acceptance"]
  D --> P["Prometheus backup timestamp"]
```
