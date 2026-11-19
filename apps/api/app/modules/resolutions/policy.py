"""Approval policy engine.

Policy is deterministic, explainable and evaluated on the backend. AI suggestions cannot
lower the risk level or bypass an approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config.settings import settings
from app.domain.enums import RiskLevel, RoleCode
from app.modules.resolutions.actions import ActionDefinition

RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


def max_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    return a if RISK_ORDER[a] >= RISK_ORDER[b] else b


@dataclass(slots=True)
class PolicyDecision:
    risk_level: RiskLevel
    requires_approval: bool
    reasons: list[str]
    approver_role: str
    allow_self_approval: bool


def evaluate_policy(
    *,
    definition: ActionDefinition,
    requested_risk: RiskLevel | str | None,
    org_settings: dict[str, Any] | None,
    requester_role: RoleCode | None = None,
) -> PolicyDecision:
    settings_map = (org_settings or {}).get("approval_policy", {}) if org_settings else {}
    threshold_name = str(settings_map.get("approval_required_risk", "HIGH")).upper()
    try:
        threshold = RiskLevel(threshold_name)
    except ValueError:
        threshold = RiskLevel.HIGH
    allow_self = bool(settings_map.get("allow_self_approval", settings.ALLOW_SELF_APPROVAL))

    requested = RiskLevel(requested_risk) if requested_risk else definition.default_risk
    risk = max_risk(definition.default_risk, requested)
    reasons: list[str] = []
    requires = False

    if RISK_ORDER[risk] >= RISK_ORDER[threshold]:
        requires = True
        reasons.append(f"Risk level {risk.value} meets the approval threshold ({threshold.value}).")
    if definition.financial_impact:
        requires = True
        reasons.append("The action has financial impact.")
    if definition.external_side_effect:
        requires = True
        reasons.append("The action contacts an external party.")
    if risk == RiskLevel.CRITICAL:
        requires = True
        reasons.append("Critical-risk actions always require approval.")
    if not requires:
        reasons.append("Low-risk internal action within the configured approval threshold.")

    approver_role = RoleCode.ORG_ADMIN.value if RISK_ORDER[risk] >= RISK_ORDER[RiskLevel.HIGH] else RoleCode.OPERATIONS_MANAGER.value
    return PolicyDecision(
        risk_level=risk,
        requires_approval=requires,
        reasons=reasons,
        approver_role=approver_role,
        allow_self_approval=allow_self,
    )
