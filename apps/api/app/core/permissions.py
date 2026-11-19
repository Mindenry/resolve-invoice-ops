"""RBAC catalog: permission codes and the default role -> permission matrix."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import RoleCode


@dataclass(frozen=True)
class PermissionDef:
    code: str
    description: str
    group: str


PERMISSIONS: tuple[PermissionDef, ...] = (
    # Cases
    PermissionDef("case:read", "View cases and their related records", "Cases"),
    PermissionDef("case:create", "Create cases manually", "Cases"),
    PermissionDef("case:update", "Edit case fields, status and priority", "Cases"),
    PermissionDef("case:assign", "Assign or reassign cases", "Cases"),
    PermissionDef("case:comment", "Add comments and internal notes", "Cases"),
    PermissionDef("case:close", "Resolve, close or cancel cases", "Cases"),
    PermissionDef("case:merge", "Merge duplicate cases", "Cases"),
    # Exceptions
    PermissionDef("exception:read", "View exceptions", "Exceptions"),
    PermissionDef("exception:triage", "Acknowledge, ignore or triage exceptions", "Exceptions"),
    # Documents
    PermissionDef("document:read", "View and download documents", "Documents"),
    PermissionDef("document:upload", "Upload documents", "Documents"),
    PermissionDef("document:delete", "Delete documents", "Documents"),
    PermissionDef("document:review", "Review and correct document extractions", "Documents"),
    # Invoices
    PermissionDef("invoice:read", "View invoices", "Invoices"),
    PermissionDef("invoice:create", "Create invoices", "Invoices"),
    PermissionDef("invoice:update", "Edit invoices and run validation", "Invoices"),
    PermissionDef("invoice:approve", "Approve invoices for downstream export", "Invoices"),
    # Vendors
    PermissionDef("vendor:read", "View vendors", "Vendors"),
    PermissionDef("vendor:create", "Create vendors", "Vendors"),
    PermissionDef("vendor:update", "Edit vendors", "Vendors"),
    PermissionDef("vendor:delete", "Archive vendors", "Vendors"),
    PermissionDef("vendor:merge", "Merge duplicate vendors", "Vendors"),
    # Purchase orders
    PermissionDef("po:read", "View purchase orders", "Purchase Orders"),
    PermissionDef("po:create", "Create purchase orders", "Purchase Orders"),
    PermissionDef("po:update", "Edit purchase orders", "Purchase Orders"),
    # Investigation / AI
    PermissionDef("investigation:read", "View AI investigations", "Investigation"),
    PermissionDef("investigation:run", "Run AI investigations", "Investigation"),
    # Resolutions / approvals
    PermissionDef("resolution:read", "View resolution proposals", "Resolutions"),
    PermissionDef("resolution:propose", "Propose resolution actions", "Resolutions"),
    PermissionDef("resolution:execute", "Execute approved resolution actions", "Resolutions"),
    PermissionDef("approval:read", "View approval requests", "Approvals"),
    PermissionDef("approval:decide", "Approve or reject requests", "Approvals"),
    # Automation
    PermissionDef("integration:read", "View integrations", "Automation"),
    PermissionDef("integration:manage", "Create and configure integrations", "Automation"),
    PermissionDef("workflow:read", "View workflow executions", "Automation"),
    PermissionDef("workflow:run", "Trigger and retry workflows", "Automation"),
    # Platform
    PermissionDef("notification:read", "View notifications", "Platform"),
    PermissionDef("analytics:read", "View analytics and dashboards", "Platform"),
    PermissionDef("audit:read", "View audit logs", "Administration"),
    PermissionDef("evaluation:read", "View AI evaluation results", "AI Evaluation"),
    PermissionDef("evaluation:run", "Run AI evaluations", "AI Evaluation"),
    PermissionDef("org:read", "View organization settings", "Administration"),
    PermissionDef("org:update", "Update organization settings", "Administration"),
    PermissionDef("user:read", "View organization members", "Administration"),
    PermissionDef("user:manage", "Invite, edit and deactivate members", "Administration"),
    PermissionDef("role:read", "View roles and permissions", "Administration"),
    PermissionDef("ai:configure", "Configure AI providers and prompts", "Administration"),
)

ALL_PERMISSIONS: frozenset[str] = frozenset(p.code for p in PERMISSIONS)

_VIEWER = {
    "case:read",
    "exception:read",
    "document:read",
    "invoice:read",
    "vendor:read",
    "po:read",
    "investigation:read",
    "resolution:read",
    "approval:read",
    "integration:read",
    "workflow:read",
    "notification:read",
    "analytics:read",
    "audit:read",
    "org:read",
    "user:read",
    "role:read",
    "evaluation:read",
}

_INVESTIGATOR = _VIEWER | {
    "case:create",
    "case:update",
    "case:comment",
    "exception:triage",
    "document:upload",
    "document:review",
    "invoice:create",
    "invoice:update",
    "investigation:run",
    "resolution:propose",
}

_APPROVER = _VIEWER | {
    "case:comment",
    "invoice:approve",
    "approval:decide",
    "resolution:execute",
    "document:review",
}

_OPERATIONS_MANAGER = _INVESTIGATOR | _APPROVER | {
    "case:assign",
    "case:close",
    "case:merge",
    "document:delete",
    "vendor:create",
    "vendor:update",
    "po:create",
    "po:update",
    "workflow:run",
    "integration:manage",
    "evaluation:run",
    "notification:read",
}

_ORG_ADMIN = ALL_PERMISSIONS

ROLE_PERMISSIONS: dict[RoleCode, frozenset[str]] = {
    RoleCode.VIEWER: frozenset(_VIEWER),
    RoleCode.INVESTIGATOR: frozenset(_INVESTIGATOR),
    RoleCode.APPROVER: frozenset(_APPROVER),
    RoleCode.OPERATIONS_MANAGER: frozenset(_OPERATIONS_MANAGER),
    RoleCode.ORG_ADMIN: frozenset(_ORG_ADMIN),
    RoleCode.SUPER_ADMIN: ALL_PERMISSIONS,
}

ROLE_LABELS: dict[RoleCode, str] = {
    RoleCode.SUPER_ADMIN: "Super Admin",
    RoleCode.ORG_ADMIN: "Organization Admin",
    RoleCode.OPERATIONS_MANAGER: "Operations Manager",
    RoleCode.INVESTIGATOR: "Investigator",
    RoleCode.APPROVER: "Approver",
    RoleCode.VIEWER: "Viewer",
}

ROLE_DESCRIPTIONS: dict[RoleCode, str] = {
    RoleCode.SUPER_ADMIN: "Platform operator with full access to every organization.",
    RoleCode.ORG_ADMIN: "Full control of a single organization, its users and configuration.",
    RoleCode.OPERATIONS_MANAGER: "Manages queues, assignments, automations and approvals.",
    RoleCode.INVESTIGATOR: "Investigates exceptions, reviews documents and proposes resolutions.",
    RoleCode.APPROVER: "Reviews and decides on high-risk actions requested by others.",
    RoleCode.VIEWER: "Read-only access to operational data.",
}

ROLE_RANK: dict[RoleCode, int] = {
    RoleCode.VIEWER: 10,
    RoleCode.APPROVER: 20,
    RoleCode.INVESTIGATOR: 30,
    RoleCode.OPERATIONS_MANAGER: 40,
    RoleCode.ORG_ADMIN: 50,
    RoleCode.SUPER_ADMIN: 60,
}


def has_permission(granted: frozenset[str] | set[str], required: str) -> bool:
    return required in granted


def role_can(role: RoleCode, required: str) -> bool:
    return required in ROLE_PERMISSIONS[role]
