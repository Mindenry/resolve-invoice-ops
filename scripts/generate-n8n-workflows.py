"""Generate the five real RESOLVE n8n workflows.

The generated JSON contains no secrets: HMAC material, SMTP host and API
credentials are read at runtime from n8n environment variables or the n8n
credential store. Run this script after provision-n8n-credential.py so the SMTP
credential id can be embedded.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

OUT = Path("infrastructure/n8n/workflows")
OUT.mkdir(parents=True, exist_ok=True)

MAILPIT_TO = "ops@resolve.local"
API = "http://api:8000"


def smtp_credential_id() -> str:
    env = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in Path(".env").read_text(encoding="utf-8").splitlines()
        if "=" in line
    }
    client = httpx.Client(base_url="http://127.0.0.1:5679", timeout=30)
    client.post(
        "/rest/login",
        json={
            "emailOrLdapLoginId": env["N8N_OWNER_EMAIL"],
            "password": env["N8N_OWNER_PASSWORD"],
        },
    ).raise_for_status()
    client.headers.update({"browser-id": "resolve-workflow-generator"})
    response = client.get("/rest/credentials", params={"includeData": "false"})
    response.raise_for_status()
    for item in response.json().get("data", []):
        if item.get("name") == "RESOLVE Mailpit SMTP":
            return item["id"]
    raise SystemExit("RESOLVE Mailpit SMTP credential not found")


VERIFY_JS = r"""
// Verify the RESOLVE HMAC-SHA256 signature over the exact raw request body and
// validate the payload schema. Idempotency is enforced separately against the
// RESOLVE claim store (Redis) so retried deliveries cannot be processed twice.
const crypto = require('crypto');
const item = $input.first();
const headers = item.json.headers || {};
const raw = item.binary && item.binary.data && item.binary.data.data
  ? Buffer.from(item.binary.data.data, 'base64').toString('utf8')
  : JSON.stringify(item.json.body || {});
const signature = String(headers['x-resolve-signature'] || headers['X-Resolve-Signature'] || '');
const secret = $env.RESOLVE_N8N_WEBHOOK_SECRET || '';
if (!secret) { throw new Error('RESOLVE_N8N_WEBHOOK_SECRET is not configured in n8n'); }
const expected = crypto.createHmac('sha256', secret).update(raw, 'utf8').digest('hex');
if (!signature || signature.length !== expected.length ||
    !crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature))) {
  throw new Error('Invalid RESOLVE webhook signature');
}
let payload;
try {
  payload = JSON.parse(raw);
} catch (error) {
  throw new Error('Malformed RESOLVE payload: expected JSON');
}
if (!payload || typeof payload !== 'object' || !payload.id || !payload.event_type) {
  throw new Error('Malformed RESOLVE payload: id and event_type are required');
}
return [{
  json: {
    signature_valid: true,
    event_id: payload.id,
    event_type: payload.event_type,
    occurred_at: payload.occurred_at || null,
    entity_type: payload.entity_type || null,
    entity_id: payload.entity_id || null,
    data: payload.data || {},
  },
}];
""".strip()

MERGE_CLAIM_JS = r"""
// Re-attach the verified event to the idempotency verdict. A repeated delivery
// of the same event id gets claimed=false and is answered as a duplicate.
const event = $('Verify signature').first().json;
const claim = $json || {};
return [{ json: { ...event, claimed: claim.claimed === true } }];
""".strip()

DEDUPE_STORE_JS = r"""
// (unused placeholder removed)
""".strip()


def node_id(prefix: str, index: int) -> str:
    return f"{prefix}-{index}"


def webhook(name: str, nid: str, path: str, pos: list[int]) -> dict:
    return {
        "parameters": {
            "httpMethod": "POST",
            "path": path,
            "responseMode": "responseNode",
            "options": {"rawBody": True},
        },
        "id": nid,
        "name": name,
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": pos,
        "webhookId": nid,
    }


def code(name: str, nid: str, js: str, pos: list[int]) -> dict:
    return {
        "parameters": {"jsCode": js, "mode": "runOnceForAllItems"},
        "id": nid,
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": pos,
    }


def if_node(name: str, nid: str, expression: str, pos: list[int], op: str = "true") -> dict:
    operator = {"type": "boolean", "operation": op, "singleValue": True}
    return {
        "parameters": {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "strict",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": nid + "-cond",
                        "leftValue": expression,
                        "rightValue": "",
                        "operator": operator,
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
        "id": nid,
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": pos,
    }


def respond(name: str, nid: str, body: str, pos: list[int]) -> dict:
    return {
        "parameters": {
            "respondWith": "json",
            "responseBody": body,
            "options": {},
        },
        "id": nid,
        "name": name,
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": pos,
    }


def email(name: str, nid: str, subject: str, text: str, pos: list[int], cred_id: str) -> dict:
    return {
        "parameters": {
            "fromEmail": "automation@resolve.local",
            "toEmail": MAILPIT_TO,
            "subject": subject,
            "emailFormat": "text",
            "text": text,
            "options": {},
        },
        "id": nid,
        "name": name,
        "type": "n8n-nodes-base.emailSend",
        "typeVersion": 2.1,
        "position": pos,
        "credentials": {"smtp": {"id": cred_id, "name": "RESOLVE Mailpit SMTP"}},
    }


def http(
    name: str,
    nid: str,
    method: str,
    url: str,
    pos: list[int],
    headers: list[dict] | None = None,
    json_body: str | None = None,
    timeout: int = 15000,
    continue_on_error: bool = False,
) -> dict:
    parameters: dict = {
        "method": method,
        "url": url,
        "options": {"timeout": timeout, "redirect": {"redirect": {}}},
    }
    if headers:
        parameters["sendHeaders"] = True
        parameters["headerParameters"] = {"parameters": headers}
    if json_body is not None:
        parameters["sendBody"] = True
        parameters["specifyBody"] = "json"
        parameters["jsonBody"] = json_body
    node = {
        "parameters": parameters,
        "id": nid,
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": pos,
    }
    if continue_on_error:
        node["onError"] = "continueRegularOutput"
    return node


def claim_node(prefix: str, pos: list[int]) -> dict:
    return http(
        "Claim event id",
        f"http-claims-{prefix}",
        "POST",
        f"{API}/api/v1/internal/automation/claims",
        pos,
        headers=[
            {"name": "X-Automation-Secret", "value": "={{ $env.RESOLVE_N8N_WEBHOOK_SECRET }}"}
        ],
        json_body="={{ JSON.stringify({ key: $json.event_id }) }}",
        timeout=8000,
    )


def schedule(name: str, nid: str, rule: dict, pos: list[int]) -> dict:
    return {
        "parameters": {"rule": {"interval": [rule]}},
        "id": nid,
        "name": name,
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": pos,
    }


def noop(name: str, nid: str, pos: list[int]) -> dict:
    return {
        "parameters": {},
        "id": nid,
        "name": name,
        "type": "n8n-nodes-base.noOp",
        "typeVersion": 1,
        "position": pos,
    }


def connect(*links: tuple[str, str]) -> dict:
    """Build connections from (from_name -> to_name) pairs.

    For IF nodes the caller passes the same source twice to indicate
    true/false outputs; this helper keeps ordering as given.
    """
    result: dict[str, dict] = {}
    for source, target in links:
        entry = result.setdefault(source, {"main": []})
        if not entry["main"]:
            entry["main"].append([])
        entry["main"][0].append({"node": target, "type": "main", "index": 0})
    return result


def workflow(name: str, wid: str, nodes: list[dict], links: list, tags: list[str]) -> dict:
    return {
        "id": wid,
        "name": name,
        "nodes": nodes,
        "connections": links,
        "active": True,
        "settings": {
            "executionOrder": "v1",
            "saveManualExecutions": True,
            "callerPolicy": "workflowsFromSameOwner",
            "timezone": "Asia/Bangkok",
            "executionTimeout": 300,
        },
        "staticData": None,
        "meta": {"templateCredsSetupCompleted": True},
        "tags": [{"name": t} for t in tags],
        "pinData": {},
        "versionId": "1",
    }


def workflow_a(cred: str) -> dict:
    nodes = [
        webhook("RESOLVE event", "wh-a", "resolve/new-exception", [0, 0]),
        code("Verify signature", "code-a", VERIFY_JS, [220, 0]),
        claim_node("a", [440, 0]),
        code("Merge claim", "code-a-merge", MERGE_CLAIM_JS, [660, 0]),
        if_node("Duplicate?", "if-a", "={{ !$json.claimed }}", [880, 0]),
        respond(
            "Respond duplicate",
            "resp-a-dup",
            "={{ JSON.stringify({ status: 'duplicate', event_id: $json.event_id }) }}",
            [1100, -140],
        ),
        email(
            "Notify operations",
            "mail-a",
            "=RESOLVE {{$json.event_type}} - {{$json.data.title || $json.data.case_number || $json.event_id}}",
            "={{ ['RESOLVE automation notification','Event: ' + $json.event_type,'Event ID: ' + $json.event_id,"
            "'Occurred: ' + ($json.occurred_at || 'n/a'),'Entity: ' + ($json.entity_type || 'n/a') + ' ' + ($json.entity_id || ''),"
            "'Severity: ' + ($json.data.severity || 'n/a'),'Priority: ' + ($json.data.priority || 'n/a'),"
            "'Title: ' + ($json.data.title || $json.data.case_number || 'n/a'),"
            "'Details: ' + JSON.stringify($json.data)].join('\\n') }}",
            [1100, 0],
            cred,
        ),
        respond(
            "Respond accepted",
            "resp-a-ok",
            "={{ JSON.stringify({ status: 'accepted', event_id: $json.event_id }) }}",
            [1320, 0],
        ),
    ]
    connections = {
        "RESOLVE event": {"main": [[{"node": "Verify signature", "type": "main", "index": 0}]]},
        "Verify signature": {"main": [[{"node": "Claim event id", "type": "main", "index": 0}]]},
        "Claim event id": {"main": [[{"node": "Merge claim", "type": "main", "index": 0}]]},
        "Merge claim": {"main": [[{"node": "Duplicate?", "type": "main", "index": 0}]]},
        "Duplicate?": {
            "main": [
                [{"node": "Respond duplicate", "type": "main", "index": 0}],
                [{"node": "Notify operations", "type": "main", "index": 0}],
            ]
        },
        "Notify operations": {
            "main": [[{"node": "Respond accepted", "type": "main", "index": 0}]]
        },
    }
    return workflow("RESOLVE A - New exception and case notification", "resolve-a-new-exception", nodes, connections, ["resolve", "workflow-a"])


def workflow_b(cred: str) -> dict:
    login_body = (
        "={{ JSON.stringify({ email: $env.RESOLVE_AUTOMATION_EMAIL, "
        "password: $env.RESOLVE_AUTOMATION_PASSWORD, "
        "organization_slug: $env.RESOLVE_ORGANIZATION_SLUG }) }}"
    )
    assess_js = r"""
// Confirm the case belongs to the automation tenant, then decide whether this
// event is a real escalation (urgent/high priority or an SLA breach).
const event = $('Verify signature').first().json;
const account = $('Login as automation').first().json;
const detail = $json || {};
const tenantOk = detail.org_id == null || account.organization.id === detail.org_id;
const priority = String(detail.priority || event.data.priority || event.data.current || '').toUpperCase();
const status = String(detail.status || '').toUpperCase();
const closed = ['RESOLVED', 'CLOSED', 'CANCELLED'].includes(status);
const dueAt = detail.due_at ? new Date(detail.due_at) : null;
const overdue = dueAt ? dueAt.getTime() < Date.now() : Boolean(detail.sla_breached);
const shouldEscalate = tenantOk && !closed && (priority === 'URGENT' || priority === 'HIGH' || overdue);
return [{
  json: {
    should_escalate: shouldEscalate,
    tenant_ok: tenantOk,
    overdue,
    priority,
    status,
    case_number: detail.case_number || event.data.case_number || 'unknown',
    case_id: event.entity_id,
    title: detail.title || event.data.title || 'n/a',
    due_at: detail.due_at || null,
    sla_breached: Boolean(detail.sla_breached),
    reason: event.data.reason || 'priority change',
    event_id: event.event_id,
    escalation_key: event.entity_id + ':' + priority + ':' + event.event_id,
  },
}];
""".strip()

    nodes = [
        webhook("RESOLVE event", "wh-b", "resolve/critical-escalation", [0, 0]),
        code("Verify signature", "code-b", VERIFY_JS, [220, 0]),
        claim_node("b", [440, 0]),
        code("Merge claim", "code-b-merge", MERGE_CLAIM_JS, [660, 0]),
        if_node("Duplicate?", "if-b-dup", "={{ !$json.claimed }}", [880, 0]),
        respond(
            "Respond duplicate",
            "resp-b-dup",
            "={{ JSON.stringify({ status: 'duplicate', event_id: $json.event_id }) }}",
            [1100, -200],
        ),
        http(
            "Login as automation",
            "http-b-login",
            "POST",
            f"{API}/api/v1/auth/login",
            [1100, 0],
            json_body=login_body,
        ),
        http(
            "Load case",
            "http-b-case",
            "GET",
            "={{ 'http://api:8000/api/v1/cases/' + $('Verify signature').first().json.entity_id }}",
            [1320, 0],
            headers=[
                {"name": "Authorization", "value": "={{ 'Bearer ' + $json.access_token }}"},
                {"name": "X-Organization-Id", "value": "={{ $json.organization.id }}"},
            ],
        ),
        code("Assess escalation", "code-b-assess", assess_js, [1540, 0]),
        if_node(
            "Escalate?",
            "if-b-escalate",
            "={{ $json.should_escalate }}",
            [1760, 0],
        ),
        email(
            "Escalate to duty manager",
            "mail-b",
            "=RESOLVE ESCALATION {{$json.priority}} {{$json.case_number}}",
            "={{ ['RESOLVE critical case escalation','Case: ' + $json.case_number + ' - ' + $json.title,"
            "'Case ID: ' + $json.case_id,'Priority: ' + $json.priority,'Status: ' + $json.status,"
            "'Due at: ' + ($json.due_at || 'n/a'),'SLA breached: ' + $json.sla_breached,"
            "'Overdue: ' + $json.overdue,'Reason: ' + $json.reason,'Event ID: ' + $json.event_id,"
            "'Action: assign an owner and approve a resolution through RESOLVE (n8n never approves or executes).']"
            ".join('\\n') }}",
            [2200, -120],
            cred,
        ),
        respond(
            "Respond escalated",
            "resp-b-escalated",
            "={{ JSON.stringify({ status: 'escalated', case: $json.case_number, priority: $json.priority }) }}",
            [2420, -120],
        ),
        respond(
            "Respond no action",
            "resp-b-none",
            "={{ JSON.stringify({ status: 'no_action', reason: $json.tenant_ok ? 'not an escalation' : 'tenant mismatch' }) }}",
            [2200, 120],
        ),
    ]
    connections = {
        "RESOLVE event": {"main": [[{"node": "Verify signature", "type": "main", "index": 0}]]},
        "Verify signature": {"main": [[{"node": "Claim event id", "type": "main", "index": 0}]]},
        "Claim event id": {"main": [[{"node": "Merge claim", "type": "main", "index": 0}]]},
        "Merge claim": {"main": [[{"node": "Duplicate?", "type": "main", "index": 0}]]},
        "Duplicate?": {
            "main": [
                [{"node": "Respond duplicate", "type": "main", "index": 0}],
                [{"node": "Login as automation", "type": "main", "index": 0}],
            ]
        },
        "Login as automation": {"main": [[{"node": "Load case", "type": "main", "index": 0}]]},
        "Load case": {"main": [[{"node": "Assess escalation", "type": "main", "index": 0}]]},
        "Assess escalation": {"main": [[{"node": "Escalate?", "type": "main", "index": 0}]]},
        "Escalate?": {
            "main": [
                [{"node": "Escalate to duty manager", "type": "main", "index": 0}],
                [{"node": "Respond no action", "type": "main", "index": 0}],
            ]
        },
        "Escalate to duty manager": {"main": [[{"node": "Respond escalated", "type": "main", "index": 0}]]},
    }
    return workflow("RESOLVE B - Critical case escalation", "resolve-b-critical-escalation", nodes, connections, ["resolve", "workflow-b"])


def workflow_c(cred: str) -> dict:
    login_body = (
        "={{ JSON.stringify({ email: $env.RESOLVE_AUTOMATION_EMAIL, "
        "password: $env.RESOLVE_AUTOMATION_PASSWORD, "
        "organization_slug: $env.RESOLVE_ORGANIZATION_SLUG }) }}"
    )
    summary_js = r"""
// Build a daily operations summary from the live analytics endpoint.
const account = $('Login as automation').first().json;
const overview = $json || {};
const kpis = {};
for (const kpi of overview.kpis || []) { kpis[kpi.key] = kpi; }
const counts = overview.counts || {};
const sla = overview.sla || {};
const processing = overview.processing || {};
const lines = [
  'RESOLVE daily operations summary',
  'Generated: ' + new Date().toISOString() + ' (Asia/Bangkok schedule)',
  '',
  'Cases and exceptions',
  '- Open cases: ' + (kpis.open_cases ? kpis.open_cases.value : 'n/a'),
  '- Critical cases: ' + (kpis.critical_cases ? kpis.critical_cases.value : 'n/a'),
  '- High priority cases: ' + (kpis.high_priority_cases ? kpis.high_priority_cases.value : 'n/a'),
  '- Open exceptions: ' + (counts.open_exceptions ?? 'n/a'),
  '- Exceptions in window: ' + (counts.exceptions_in_range ?? 'n/a'),
  '',
  'Resolution',
  '- Resolved today: ' + (kpis.resolved_today ? kpis.resolved_today.value : 'n/a'),
  '- Average resolution hours: ' + (sla.average_resolution_hours ?? 'n/a'),
  '- SLA breached: ' + (sla.breached ?? 'n/a'),
  '- Due within 24h: ' + (sla.due_within_24h ?? 'n/a'),
  '',
  'Approvals and processing',
  '- Pending approvals: ' + (kpis.pending_approvals ? kpis.pending_approvals.value : 'n/a'),
  '- Failed jobs: ' + (processing.failed_jobs ?? 'n/a'),
  '- AI runs: ' + (processing.ai_runs ?? 'n/a'),
  '',
  'Tenant: ' + account.organization.name,
  'Source: RESOLVE /api/v1/analytics/overview (window ' + (overview.range_days ?? 'n/a') + ' days)',
  'No personal data beyond aggregate counts is included in this summary.',
];
return [{ json: { summary: lines.join('\n'), open_cases: kpis.open_cases ? kpis.open_cases.value : null } }];
""".strip()
    nodes = [
        schedule(
            "Daily at 08:00 Bangkok",
            "sched-c",
            {"field": "cronExpression", "expression": "0 8 * * *"},
            [0, 0],
        ),
        http(
            "Login as automation",
            "http-c-login",
            "POST",
            f"{API}/api/v1/auth/login",
            [220, 0],
            json_body=login_body,
        ),
        http(
            "Load analytics",
            "http-c-analytics",
            "GET",
            f"{API}/api/v1/analytics/overview?days=7",
            [440, 0],
            headers=[
                {"name": "Authorization", "value": "={{ 'Bearer ' + $json.access_token }}"},
                {"name": "X-Organization-Id", "value": "={{ $json.organization.id }}"},
            ],
        ),
        code("Build summary", "code-c", summary_js, [660, 0]),
        email(
            "Send daily summary",
            "mail-c",
            "=RESOLVE daily operations summary - {{ $now.setZone('Asia/Bangkok').toFormat('yyyy-MM-dd') }}",
            "={{ $json.summary }}",
            [880, 0],
            cred,
        ),
    ]
    connections = {
        "Daily at 08:00 Bangkok": {"main": [[{"node": "Login as automation", "type": "main", "index": 0}]]},
        "Login as automation": {"main": [[{"node": "Load analytics", "type": "main", "index": 0}]]},
        "Load analytics": {"main": [[{"node": "Build summary", "type": "main", "index": 0}]]},
        "Build summary": {"main": [[{"node": "Send daily summary", "type": "main", "index": 0}]]},
    }
    return workflow("RESOLVE C - Daily operations summary", "resolve-c-daily-summary", nodes, connections, ["resolve", "workflow-c"])


def workflow_d(cred: str) -> dict:
    login_body = (
        "={{ JSON.stringify({ email: $env.RESOLVE_AUTOMATION_EMAIL, "
        "password: $env.RESOLVE_AUTOMATION_PASSWORD, "
        "organization_slug: $env.RESOLVE_ORGANIZATION_SLUG }) }}"
    )
    assess_js = r"""
// Decide whether a failed document needs a retry or a human. Retries are never
// performed by n8n: it reports the failure and the operator retriggers through
// RESOLVE, which keeps OCR limits and approvals under platform control.
const event = $('Verify signature').first().json;
const detail = $json || {};
const status = String(detail.status || event.data.status || '').toUpperCase();
const attempts = Number(event.data.attempts || 0);
const shouldNotify = status === 'FAILED' || Boolean(event.data.error);
const errorText = String(detail.processing_error || event.data.error || '').slice(0, 500);
return [{
  json: {
    should_notify: shouldNotify,
    document_id: event.entity_id,
    filename: detail.original_filename || event.data.filename || 'unknown',
    status: status || 'UNKNOWN',
    attempts,
    retry_recommended: attempts < 3,
    error: errorText,
    event_id: event.event_id,
    dedupe_key: event.entity_id + ':' + event.event_id,
  },
}];
""".strip()
    nodes = [
        webhook("RESOLVE event", "wh-d", "resolve/document-failure", [0, 0]),
        code("Verify signature", "code-d", VERIFY_JS, [220, 0]),
        claim_node("d", [440, 0]),
        code("Merge claim", "code-d-merge", MERGE_CLAIM_JS, [660, 0]),
        if_node("Duplicate?", "if-d-dup", "={{ !$json.claimed }}", [880, 0]),
        respond(
            "Respond duplicate",
            "resp-d-dup",
            "={{ JSON.stringify({ status: 'duplicate', event_id: $json.event_id }) }}",
            [1100, -200],
        ),
        http(
            "Login as automation",
            "http-d-login",
            "POST",
            f"{API}/api/v1/auth/login",
            [1100, 0],
            json_body=login_body,
        ),
        http(
            "Load document",
            "http-d-doc",
            "GET",
            "={{ 'http://api:8000/api/v1/documents/' + $('Verify signature').first().json.entity_id }}",
            [1320, 0],
            headers=[
                {"name": "Authorization", "value": "={{ 'Bearer ' + $json.access_token }}"},
                {"name": "X-Organization-Id", "value": "={{ $json.organization.id }}"},
            ],
        ),
        code("Assess failure", "code-d-assess", assess_js, [1540, 0]),
        if_node("Notify?", "if-d-notify", "={{ $json.should_notify }}", [1760, 0]),
        email(
            "Notify document owners",
            "mail-d",
            "=RESOLVE document processing failed - {{$json.filename}}",
            "={{ ['RESOLVE document processing failure','Document: ' + $json.filename,'Document ID: ' + $json.document_id,"
            "'Status: ' + $json.status,'Recorded attempts: ' + $json.attempts,"
            "'Retry recommended: ' + $json.retry_recommended,"
            "'Error: ' + ($json.error || 'n/a'),'Event ID: ' + $json.event_id,"
            "'Next step: review the document in RESOLVE and use Reprocess when the source file is valid.']"
            ".join('\\n') }}",
            [1980, -120],
            cred,
        ),
        respond(
            "Respond notified",
            "resp-d-ok",
            "={{ JSON.stringify({ status: 'notified', document: $json.document_id }) }}",
            [2200, -120],
        ),
        respond(
            "Respond ignored",
            "resp-d-ignore",
            "={{ JSON.stringify({ status: 'no_action', reason: 'document not in failed state' }) }}",
            [1980, 120],
        ),
    ]
    connections = {
        "RESOLVE event": {"main": [[{"node": "Verify signature", "type": "main", "index": 0}]]},
        "Verify signature": {"main": [[{"node": "Claim event id", "type": "main", "index": 0}]]},
        "Claim event id": {"main": [[{"node": "Merge claim", "type": "main", "index": 0}]]},
        "Merge claim": {"main": [[{"node": "Duplicate?", "type": "main", "index": 0}]]},
        "Duplicate?": {
            "main": [
                [{"node": "Respond duplicate", "type": "main", "index": 0}],
                [{"node": "Login as automation", "type": "main", "index": 0}],
            ]
        },
        "Login as automation": {"main": [[{"node": "Load document", "type": "main", "index": 0}]]},
        "Load document": {"main": [[{"node": "Assess failure", "type": "main", "index": 0}]]},
        "Assess failure": {"main": [[{"node": "Notify?", "type": "main", "index": 0}]]},
        "Notify?": {
            "main": [
                [{"node": "Notify document owners", "type": "main", "index": 0}],
                [{"node": "Respond ignored", "type": "main", "index": 0}],
            ]
        },
        "Notify document owners": {"main": [[{"node": "Respond notified", "type": "main", "index": 0}]]},
    }
    return workflow("RESOLVE D - Document processing failure", "resolve-d-document-failure", nodes, connections, ["resolve", "workflow-d"])


def workflow_e(cred: str) -> dict:
    summary_js = r"""
// Aggregate the live probes into one health verdict.
const api = $('Probe API').first().json || {};
const ollama = $('Probe Ollama').first().json || {};
const n8n = $('Probe n8n').first().json || {};
const prom = $('Probe worker count').first().json || {};
const apiOk = !api.error && String(api.status || '') === 'ready';
const ollamaOk = !ollama.error && Boolean(ollama.version);
const n8nOk = !n8n.error && (n8n === true || n8n.status === 'ok' || Boolean(n8n.ok));
let workers = null;
try {
  const result = prom.data && prom.data.result ? prom.data.result : [];
  workers = result.length ? Number(result[0].value[1]) : 0;
} catch (error) { workers = null; }
const workerOk = workers === null ? !prom.error : workers > 0;
const components = (api.components || {});
const databaseOk = components.database ? components.database.status === 'ok' : false;
const redisOk = components.redis ? components.redis.status === 'ok' : false;
const storageOk = components.storage ? components.storage.status === 'ok' : false;
const degraded = !(apiOk && ollamaOk && n8nOk && workerOk && databaseOk && redisOk && storageOk);
const lines = [
  'RESOLVE integration health monitor',
  'Checked: ' + new Date().toISOString(),
  '',
  'API: ' + (apiOk ? 'ready' : 'DOWN'),
  'Database: ' + (databaseOk ? 'ok' : 'DOWN'),
  'Redis: ' + (redisOk ? 'ok' : 'DOWN'),
  'Object storage: ' + (storageOk ? 'ok' : 'DOWN'),
  'Celery workers: ' + (workers === null ? 'unknown' : workers),
  'Ollama: ' + (ollamaOk ? 'reachable' : 'unreachable'),
  'n8n: ' + (n8nOk ? 'healthy' : 'unhealthy'),
];
return [{ json: { degraded, summary: lines.join('\n'), workers } }];
""".strip()
    nodes = [
        schedule(
            "Every 5 minutes",
            "sched-e",
            {"field": "cronExpression", "expression": "*/5 * * * *"},
            [0, 0],
        ),
        http(
            "Probe API",
            "http-e-api",
            "GET",
            f"{API}/health/ready",
            [220, -200],
            timeout=8000,
            continue_on_error=True,
        ),
        http(
            "Probe Ollama",
            "http-e-ollama",
            "GET",
            "http://host.docker.internal:11434/api/version",
            [220, 0],
            timeout=8000,
            continue_on_error=True,
        ),
        http(
            "Probe n8n",
            "http-e-n8n",
            "GET",
            "http://n8n:5678/healthz",
            [220, 200],
            timeout=8000,
            continue_on_error=True,
        ),
        http(
            "Probe worker count",
            "http-e-prom",
            "GET",
            "http://prometheus:9090/api/v1/query?query=sum(celery_worker_up)",
            [220, 400],
            timeout=8000,
            continue_on_error=True,
        ),
        code("Assess health", "code-e", summary_js, [460, 100]),
        if_node("Degraded?", "if-e", "={{ $json.degraded }}", [700, 100]),
        email(
            "Alert on degraded services",
            "mail-e",
            "=RESOLVE health alert - {{ $now.setZone('Asia/Bangkok').toFormat('yyyy-MM-dd HH:mm') }}",
            "={{ $json.summary }}",
            [940, -40],
            cred,
        ),
        noop("Healthy", "noop-e", [940, 240]),
    ]
    connections = {
        "Every 5 minutes": {"main": [[{"node": "Probe API", "type": "main", "index": 0}]]},
        "Probe API": {"main": [[{"node": "Probe Ollama", "type": "main", "index": 0}]]},
        "Probe Ollama": {"main": [[{"node": "Probe n8n", "type": "main", "index": 0}]]},
        "Probe n8n": {"main": [[{"node": "Probe worker count", "type": "main", "index": 0}]]},
        "Probe worker count": {"main": [[{"node": "Assess health", "type": "main", "index": 0}]]},
        "Assess health": {"main": [[{"node": "Degraded?", "type": "main", "index": 0}]]},
        "Degraded?": {
            "main": [
                [{"node": "Alert on degraded services", "type": "main", "index": 0}],
                [{"node": "Healthy", "type": "main", "index": 0}],
            ]
        },
    }
    return workflow("RESOLVE E - Integration health monitor", "resolve-e-health-monitor", nodes, connections, ["resolve", "workflow-e"])


def main() -> int:
    credential = smtp_credential_id()
    workflows = {
        "resolve-a-new-exception.json": workflow_a(credential),
        "resolve-b-critical-escalation.json": workflow_b(credential),
        "resolve-c-daily-summary.json": workflow_c(credential),
        "resolve-d-document-failure.json": workflow_d(credential),
        "resolve-e-health-monitor.json": workflow_e(credential),
    }
    for filename, payload in workflows.items():
        (OUT / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print("wrote", OUT / filename)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
