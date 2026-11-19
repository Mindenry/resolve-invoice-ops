# RESOLVE n8n workflow templates

These exports are importable templates, not pre-credentialed automations. Import them in n8n via
**Workflows ? Import from File**, then:

1. Set the environment variables used by the templates:
   - `RESOLVE_WEBHOOK_SECRET` (must match `N8N_WEBHOOK_SECRET` in the API)
   - `RESOLVE_OPS_WEBHOOK_URL` (Slack/Teams/HTTP sink)
   - `RESOLVE_OPS_EMAIL` (operations mailbox)
2. Create an SMTP credential in n8n and attach it to the "Send email" node in templates 03 and 04.
3. Activate each workflow and copy its production webhook URL into the RESOLVE Integration Hub
   (or map it in the n8n integration `workflow_webhook_map`).

RESOLVE works without n8n. When no n8n integration is enabled, workflow executions are recorded as
failed with a clear reason; the platform never reports a workflow as successful without a real call.

Templates:

| File | Trigger | Purpose |
| --- | --- | --- |
| 01-new-exception-notification.json | exception.detected | Notify the operations channel of a high-severity exception |
| 02-high-priority-escalation.json | case.escalated | Escalate urgent cases to the duty manager |
| 03-missing-document-request.json | resolution.executed | Email a vendor a missing-document request |
| 04-vendor-confirmation-email.json | resolution.executed | Email a vendor an invoice confirmation request |
| 05-approval-notification.json | approval.requested | Notify approvers of a pending high-risk request |
| 06-case-resolution-notification.json | case.resolved | Announce resolutions to the reporting channel |
| 07-failed-integration-recovery.json | integration.failed | Alert on repeated integration failures |
