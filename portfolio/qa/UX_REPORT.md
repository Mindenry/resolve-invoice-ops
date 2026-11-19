# Portfolio capture QA

- App: https://192.168.1.107:8180
- Viewports tested: desktop 1440x900, tablet 834x1112, mobile 390x844
- Routes per viewport: 8
- Horizontal overflow failures: 0
- App console/page errors captured: 0
- External UI console messages (n8n/grafana, non-blocking): 2
- n8n capture: ok
- Grafana capture: ok

## Overflow results

| Viewport | Route | Overflow px | Status |
| --- | --- | --- | --- |
| desktop | / | 0 | PASS |
| desktop | /invoices | 0 | PASS |
| desktop | /exceptions | 0 | PASS |
| desktop | /cases | 0 | PASS |
| desktop | /documents | 0 | PASS |
| desktop | /approvals | 0 | PASS |
| desktop | /analytics | 0 | PASS |
| desktop | /settings | 0 | PASS |
| tablet | / | 0 | PASS |
| tablet | /invoices | 0 | PASS |
| tablet | /exceptions | 0 | PASS |
| tablet | /cases | 0 | PASS |
| tablet | /documents | 0 | PASS |
| tablet | /approvals | 0 | PASS |
| tablet | /analytics | 0 | PASS |
| tablet | /settings | 0 | PASS |
| mobile | / | 0 | PASS |
| mobile | /invoices | 0 | PASS |
| mobile | /exceptions | 0 | PASS |
| mobile | /cases | 0 | PASS |
| mobile | /documents | 0 | PASS |
| mobile | /approvals | 0 | PASS |
| mobile | /analytics | 0 | PASS |
| mobile | /settings | 0 | PASS |

## Console errors

None captured.

## External UI console messages

- n8n: Failed to load resource: the server responded with a status of 401 (Unauthorized)
- n8n: Error: injectNDVStore() was accessed without an active workflow document store. Derive the NDV store from injectWorkflowDocumentStore().value.documentId in contexts that can run without a loaded workf
