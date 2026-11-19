# RESOLVE integration SDK

```python
from resolve_sdk import ResolveClient, verify_inbound_webhook

with ResolveClient("http://localhost:8000") as client:
    client.login("admin@example.com", os.environ["RESOLVE_DEMO_PASSWORD"], "northwind")
    open_cases = client.list_cases(status="OPEN")
```

`inbound_webhook_signature(body, secret)` produces the `X-Resolve-Signature` value expected by
`POST /api/v1/webhooks/{integration_id}`. Webhook deliveries are idempotent on the
`Idempotency-Key` header / `id` field.