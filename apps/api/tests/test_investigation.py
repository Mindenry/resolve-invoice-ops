"""AI investigation, evidence validation and provider failure tests."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.ai.base import LLMResult
from app.ai.client import run_coroutine_safely, structured_completion
from app.domain.enums import RoleCode
from app.models.ai import Investigation
from app.modules.cases.service import create_case
from app.modules.exceptions import service as exception_service
from app.modules.investigation import service as investigation_service
from app.modules.investigation.schemas import InvestigationModelOutput
from tests.conftest import OrgFixture
from tests.factories import make_invoice, make_vendor


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def complete(self, messages, **kwargs):  # noqa: ANN001
        self.calls += 1
        return LLMResult(
            content=json.dumps(self.payload),
            provider=self.name,
            model=self.model,
            input_tokens=100,
            output_tokens=50,
            latency_ms=12,
        )

    async def health(self):  # noqa: ANN201
        return True, "ok"


def _case(db, org):
    vendor = make_vendor(db, org.org.id, number="V-INV", name="Investigate Me Ltd.", tax_id="THINV")
    invoice = make_invoice(
        db, org.org.id, vendor, number="INV-INV-1", po=None, subtotal="4500.00", total="4500.00"
    )
    db.commit()
    exceptions = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    db.commit()
    case = create_case(
        db,
        org_id=org.org.id,
        actor_id=org.users[RoleCode.ORG_ADMIN].id,
        title="Missing purchase order investigation",
        priority="HIGH",
        exception_ids=[record.id for record in exceptions],
        links=[("INVOICE", invoice.id, invoice.invoice_number)],
        notify_team=False,
    )
    db.commit()
    return case, invoice, exceptions


def _valid_payload(evidence: list[dict]) -> dict:
    return {
        "summary": "Invoice has no purchase order and exceeds policy.",
        "exception_types": ["MISSING_PURCHASE_ORDER"],
        "root_cause_hypotheses": [
            {"hypothesis": "The invoice was raised without an approved commitment.", "likelihood": "high", "supporting_evidence_count": 1}
        ],
        "root_cause": "No purchase order was issued for this invoice.",
        "evidence": evidence,
        "contradicting_evidence": [],
        "missing_information": ["Purchase order"],
        "risk_assessment": {"level": "HIGH", "rationale": "Unapproved spend."},
        "suggested_resolutions": [
            {"action_type": "ESCALATE_CASE", "description": "Escalate to procurement.", "rationale": "Missing commitment.", "risk_level": "MEDIUM"}
        ],
        "required_actions": ["Obtain the purchase order"],
        "confidence": 0.7,
        "confidence_basis": "Heuristic score based on deterministic findings.",
        "limitations": ["AI output requires human confirmation."],
        "requires_human_review": True,
    }


def test_investigation_runs_end_to_end(client: TestClient, org: OrgFixture, db) -> None:
    case, invoice, _ = _case(db, org)
    response = client.post(
        f"/api/v1/cases/{case.id}/investigations",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={},
    )
    assert response.status_code == 201, response.text
    db.expire_all()
    investigations = client.get(
        f"/api/v1/cases/{case.id}/investigations", headers=org.headers[RoleCode.ORG_ADMIN]
    ).json()
    assert investigations
    investigation = investigations[0]
    assert investigation["status"] == "COMPLETED", investigation
    assert investigation["evidence_count"] > 0
    assert investigation["invalid_evidence_count"] == 0
    assert investigation["input_tokens"] > 0
    assert investigation["cost_usd"] is not None
    assert any(item["is_validated"] for item in investigation["evidence"])
    assert investigation["suggested_resolutions"]


def test_hallucinated_document_evidence_is_rejected(db, org, monkeypatch) -> None:
    case, _invoice, _ = _case(db, org)
    fake_document = str(uuid.uuid4())
    payload = _valid_payload(
        [
            {
                "source_type": "DOCUMENT",
                "source_id": fake_document,
                "document_id": fake_document,
                "page_number": 3,
                "field_name": "total",
                "quote": "Total 999.00",
                "relationship": "Fabricated",
            }
        ]
    )
    monkeypatch.setattr(
        investigation_service, "build_llm_provider", lambda: FakeProvider(payload)
    )
    investigation = Investigation(
        org_id=org.org.id,
        case_id=case.id,
        status="QUEUED",
        provider="fake",
        model="fake-model",
        prompt_version="investigation.v1",
        created_by_id=org.users[RoleCode.ORG_ADMIN].id,
    )
    db.add(investigation)
    db.commit()
    investigation = investigation_service.execute_investigation(db, investigation)
    db.commit()
    assert investigation.status.value == "COMPLETED"
    evidence = investigation_service.investigation_out(db, investigation)
    assert evidence.invalid_evidence_count == 1
    assert evidence.root_cause is None
    assert any("validation" in item.lower() or "validat" in item.lower() for item in evidence.limitations)


def test_ai_unavailable_is_recorded_not_faked(db, org, monkeypatch) -> None:
    case, _invoice, _ = _case(db, org)
    monkeypatch.setattr(investigation_service, "build_llm_provider", lambda: None)
    investigation = investigation_service.create_investigation(db, case=case, actor_id=None)
    db.commit()
    db.expire_all()
    investigation = db.get(Investigation, investigation.id)
    assert investigation.status.value == "FAILED"
    assert investigation.error_code == "ai_unavailable"
    assert investigation.requires_human_review is True


def test_structured_output_retries_invalid_json() -> None:
    class FlakyProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__({})
            self.contents = ["not json at all", json.dumps(_valid_payload([]))]

        async def complete(self, messages, **kwargs):  # noqa: ANN001
            self.calls += 1
            content = self.contents[min(self.calls - 1, len(self.contents) - 1)]
            return LLMResult(
                content=content,
                provider="fake",
                model="fake",
                input_tokens=5,
                output_tokens=5,
                latency_ms=1,
            )

    provider = FlakyProvider()
    parsed, _result, attempts = run_coroutine_safely(
        structured_completion(
            provider=provider,
            messages=[],
            schema=InvestigationModelOutput,
            schema_json=InvestigationModelOutput.model_json_schema(),
            max_attempts=3,
        )
    )
    assert isinstance(parsed, InvestigationModelOutput)
    assert attempts == 2


def test_unsupported_case_investigation_requires_permission(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, _ = _case(db, org)
    response = client.post(
        f"/api/v1/cases/{case.id}/investigations", headers=org.headers[RoleCode.VIEWER], json={}
    )
    assert response.status_code == 403


def test_evidence_requires_source_id(db, org) -> None:
    case, _invoice, _ = _case(db, org)
    from app.modules.investigation.schemas import EvidenceItem

    item = EvidenceItem(source_type="INVOICE", source_id=None, quote="Invoice total", relationship=None)
    context, _candidates, wrapper = investigation_service.build_context(
        db, org_id=org.org.id, case=case, top_k=2
    )
    valid, error = investigation_service._validate_evidence(
        db, org_id=org.org.id, allowed=wrapper["allowed"], item=item
    )
    assert valid is False
    assert "source_id" in (error or "")


def test_ai_status_endpoint(client: TestClient, org: OrgFixture) -> None:
    response = client.get("/api/v1/investigations/ai-status", headers=org.headers[RoleCode.VIEWER])
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "stub"
    assert body["deterministic_stub"] is True
    assert body["configured"] is True


@pytest.mark.parametrize("source_type", ["CHUNK", "DOCUMENT"])
def test_citation_outside_context_is_invalid(db, org, source_type) -> None:
    case, _invoice, _ = _case(db, org)
    from app.modules.investigation.schemas import EvidenceItem

    context, _candidates, wrapper = investigation_service.build_context(
        db, org_id=org.org.id, case=case, top_k=2
    )
    item = EvidenceItem(
        source_type=source_type,
        source_id=str(uuid.uuid4()),
        document_id=uuid.uuid4(),
        page_number=1,
        quote="Anything",
        relationship="Fabricated",
    )
    valid, error = investigation_service._validate_evidence(
        db, org_id=org.org.id, allowed=wrapper["allowed"], item=item
    )
    assert valid is False
    assert error

def test_ai_suggestion_creates_proposal_but_never_executes(
    client: TestClient, org: OrgFixture, db
) -> None:
    case, _invoice, _ = _case(db, org)
    client.post(
        f"/api/v1/cases/{case.id}/investigations",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={},
    )
    investigation = client.get(
        f"/api/v1/cases/{case.id}/investigations", headers=org.headers[RoleCode.ORG_ADMIN]
    ).json()[0]
    accepted = client.post(
        f"/api/v1/investigations/{investigation['id']}/suggestions/0/accept",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"suggestion_index": 0},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["status"] != "COMPLETED"

    resolution = client.get(
        f"/api/v1/resolutions/{body['resolution_id']}", headers=org.headers[RoleCode.ORG_ADMIN]
    ).json()
    assert resolution["status"] != "COMPLETED"
    assert resolution["executed_at"] is None
    assert resolution["executions"] == []
