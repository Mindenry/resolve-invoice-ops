# Final acceptance results

Run: 2026-11-19T15:15:33.577299+00:00 against `https://192.168.1.10:8180`

| ID | Scenario | Expected | Actual | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| F01 | Duplicate invoice (same vendor/number/amount) | DUPLICATE_INVOICE detected | types=['DUPLICATE_INVOICE', 'MISSING_DOCUMENTS', 'MISSING_PURCHASE_ORDER'] | **PASS** | `invoice=0a23c184-086d-4c08-a0ac-6da188645c5a` |
| F02 | Same invoice number, different vendor | No duplicate exception | types=['MISSING_DOCUMENTS', 'MISSING_PURCHASE_ORDER'] | **PASS** | `invoice=66ca2434-951c-4099-85cb-e68381fe9641` |
| F03 | Invoice amount differs from PO | AMOUNT_MISMATCH detected | types=['AMOUNT_MISMATCH', 'MISSING_DOCUMENTS'] | **PASS** | `invoice=f0a2a347-5c6a-4f48-8d14-b54999f89326` |
| F04 | VAT calculated incorrectly (12% implied, 10% line) | TAX_DISCREPANCY + line_tax_mismatch | types=['MISSING_DOCUMENTS', 'MISSING_PURCHASE_ORDER', 'TAX_DISCREPANCY'] checks=['line_tax_mismatch', 'missing_purchase_order'] | **PASS** | `invoice=1a330eba-5f72-4510-ac95-4099f2a0903a` |
| F05 | Vendor differs from PO vendor | VENDOR_MISMATCH detected | types=['AMOUNT_MISMATCH', 'MISSING_DOCUMENTS', 'VENDOR_MISMATCH'] | **PASS** | `invoice=d7e28117-5a9e-4ec7-a94a-5cea90defe5c` |
| F06 | Missing purchase order | MISSING_PURCHASE_ORDER detected | types=['MISSING_DOCUMENTS', 'MISSING_PURCHASE_ORDER'] | **PASS** | `invoice=3620f718-b05b-4662-953e-61280d213d8e` |
| F07 | Missing supporting documents | MISSING_DOCUMENTS detected | types=['MISSING_DOCUMENTS', 'MISSING_PURCHASE_ORDER'] | **PASS** | `invoice=3620f718-b05b-4662-953e-61280d213d8e` |
| F08 | Invalid (future) invoice date | future_invoice_date + INVALID_INVOICE_DATE | checks=['future_invoice_date', 'missing_purchase_order'] types=['INVALID_INVOICE_DATE', 'MISSING_DOCUMENTS', 'MISSING_PURCHASE_ORDER'] | **PASS** | `invoice=da8db021-2617-4990-a459-858607c1d04b` |
| F09 | Invalid tax information (vendor identity differs from PO) | VENDOR_MISMATCH blocks the invoice | types=['AMOUNT_MISMATCH', 'MISSING_DOCUMENTS', 'VENDOR_MISMATCH'] description=Invoice vendor differs from the purchase order vendor | **PASS** | `invoice=8a41f3bf-d78a-4eba-bc57-aad26ce6e62c` |
| F10 | Currency mismatch invoice vs PO | po_currency_mismatch FAIL | checks=['po_currency_mismatch', 'po_total_mismatch', 'vendor_currency_mismatch'] | **PASS** | `invoice=1d012733-fc60-4077-8ddf-a08e0b52faa9` |
| F11 | Partial invoice against larger PO | AMOUNT_MISMATCH flagged as partial (MEDIUM) | severity=MEDIUM | **PASS** | `invoice=a2979295-9e54-4199-a311-628e969831bf` |
| F12 | Multiple invoice lines with correct decimals | No total/line/tax arithmetic failures | checks=['missing_purchase_order'] | **PASS** | `invoice=df260d62-f1de-4ead-901f-63ce1d68a269` |
| F13 | Duplicate document upload | HTTP 409 duplicate_document with existing id | first=201 second=409 code=duplicate_document | **PASS** | `` |
| F14 | Low OCR confidence handling | requires_review or OCR confidence < 0.6 | status=REQUIRES_REVIEW confidence=0.568 | **PASS** | `` |
| F15 | Invalid file format rejected | HTTP 4xx | status=422 | **PASS** | `` |
| F16 | Corrupted document fails safely | Document status FAILED with error | status=FAILED | **PASS** | `` |
| F17 | Large file rejected | HTTP 4xx | status=422 | **PASS** | `` |
| F18 | Duplicate inbound webhook | Same event id returned, no duplicate | 202/202 | **PASS** | `` |
| F19 | Invalid webhook HMAC | HTTP 400 | status=400 | **PASS** | `` |
| F22 | Self-approval by requester | HTTP 403 | status=403 | **PASS** | `approval=88ae9646-2a7a-433f-84b8-299c021fccb8` |
| F20 | Concurrent approval of one request | Exactly one success, no duplicate decision | statuses=[200, 409] | **PASS** | `approval=44c837a3-bb7e-46b2-ad14-d19ac87ddaff` |
| F21 | Expired approval cannot be approved | HTTP 4xx | status=409 | **PASS** | `approval=de0653fc-01ca-43d8-aadb-85d39cd2513d` |
| F23 | Viewer cannot execute a resolution | HTTP 403 | status=403 | **PASS** | `resolution=73f360b5-81c9-4073-b689-06e374933dc6` |
| F24 | Cross-tenant case read | HTTP 404 | status=404 | **PASS** | `` |
| F25 | Retry after processing failure | Reprocess accepted and status re-evaluated | reprocess=200 final=FAILED | **PASS** | `` |
| R01 | Role matrix (6 roles + automation account) | All role boundaries enforced | viewer read/write=ok; investigator create case / no approval=ok; approver decides approval=ok; operations manager creates vendor=ok; org admin reads audit=ok; super admin reads platform data=ok; automation read-only=ok | **PASS** | `` |

**Summary:** 26 PASS / 0 FAIL of 26 cases.
