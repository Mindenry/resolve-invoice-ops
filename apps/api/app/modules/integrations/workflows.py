"""n8n workflow templates shipped with RESOLVE.

Each template corresponds to an export JSON under infrastructure/n8n/workflows. The API can
trigger the n8n webhook; if n8n is not configured the execution is recorded as failed with a
clear reason instead of pretending to succeed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import NotFoundError


@dataclass(frozen=True, slots=True)
class WorkflowTemplate:
    key: str
    name: str
    description: str
    trigger_event: str
    file_name: str
    required_parameters: tuple[str, ...] = ()


WORKFLOW_TEMPLATES: tuple[WorkflowTemplate, ...] = (
    WorkflowTemplate(
        key="new-exception-notification",
        name="New exception notification",
        description="Notifies the operations channel when a high-severity exception is detected.",
        trigger_event="exception.detected",
        file_name="01-new-exception-notification.json",
    ),
    WorkflowTemplate(
        key="high-priority-escalation",
        name="High priority case escalation",
        description="Escalates urgent cases to the duty manager with SLA context.",
        trigger_event="case.escalated",
        file_name="02-high-priority-escalation.json",
    ),
    WorkflowTemplate(
        key="missing-document-request",
        name="Missing document request",
        description="Emails a vendor a missing-document request after approval.",
        trigger_event="resolution.executed",
        file_name="03-missing-document-request.json",
        required_parameters=("vendor_email", "items"),
    ),
    WorkflowTemplate(
        key="vendor-confirmation-email",
        name="Vendor confirmation email",
        description="Sends a vendor invoice confirmation request.",
        trigger_event="resolution.executed",
        file_name="04-vendor-confirmation-email.json",
        required_parameters=("vendor_email", "case_number"),
    ),
    WorkflowTemplate(
        key="approval-notification",
        name="Approval notification",
        description="Notifies approvers that a new high-risk request is waiting.",
        trigger_event="approval.requested",
        file_name="05-approval-notification.json",
    ),
    WorkflowTemplate(
        key="case-resolution-notification",
        name="Case resolution notification",
        description="Announces resolved cases and records the summary in the reporting channel.",
        trigger_event="case.resolved",
        file_name="06-case-resolution-notification.json",
    ),
    WorkflowTemplate(
        key="failed-integration-recovery",
        name="Failed integration recovery",
        description="Alerts on repeated integration failures and offers a retry hook.",
        trigger_event="integration.failed",
        file_name="07-failed-integration-recovery.json",
    ),
)

_BY_KEY = {template.key: template for template in WORKFLOW_TEMPLATES}


def get_template(key: str) -> WorkflowTemplate:
    template = _BY_KEY.get(key)
    if template is None:
        raise NotFoundError(f"Unknown workflow template '{key}'.", code="workflow_template_not_found")
    return template
