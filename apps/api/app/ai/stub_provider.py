"""Deterministic stub providers.

These exist for automated tests and for running the evaluation harness without external
credentials. They are only activated by explicitly setting AI_PROVIDER=stub /
AI_EMBEDDING_PROVIDER=stub, and every produced record is labelled provider="stub".
They are NOT a semantic model and must never be enabled in production.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from app.ai.base import (
    ChatMessage,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMResult,
    ProviderError,
    Stopwatch,
    estimate_tokens,
)

_CONTEXT_RE = re.compile(r"<context_json>\s*(\{.*\})\s*</context_json>", re.DOTALL)


def _extract_context(text: str) -> dict[str, Any]:
    match = _CONTEXT_RE.search(text)
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


class StubLLMProvider(LLMProvider):
    name = "stub"

    def __init__(self, model: str = "resolve-stub-1") -> None:
        self.model = model

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2000,
        json_mode: bool = True,
        schema: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> LLMResult:
        watch = Stopwatch()
        system = next((m.content for m in messages if m.role == "system"), "")
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if "TEST:FAIL" in user:
            raise ProviderError("Stub provider instructed to fail.", retryable=False)
        if "TEST:MALFORMED" in user:
            return LLMResult("{not valid json", self.name, self.model, 10, 5, watch.elapsed_ms)
        if "TEST:TIMEOUT" in user:
            raise ProviderError("Stub provider simulated a timeout.", retryable=True)

        context = _extract_context(user)
        if "TEST:NO_CONTEXT" in user:
            context = {}
        if context.get("task") == "investigation":
            content = json.dumps(self._investigation(context, system), ensure_ascii=False)
        elif context.get("task") == "extraction":
            content = json.dumps({"fields": context.get("candidate_fields", [])}, ensure_ascii=False)
        elif context.get("task") == "resolution_validation":
            content = json.dumps({"valid": True, "notes": []}, ensure_ascii=False)
        else:
            content = json.dumps({"summary": "Stub provider response.", "requires_human_review": True})

        return LLMResult(
            content=content,
            provider=self.name,
            model=self.model,
            input_tokens=estimate_tokens(system + user),
            output_tokens=estimate_tokens(content),
            latency_ms=watch.elapsed_ms,
        )

    @staticmethod
    def _investigation(context: dict[str, Any], system: str) -> dict[str, Any]:
        case = context.get("case") or {}
        exceptions = context.get("exceptions") or []
        evidence_candidates = context.get("evidence_candidates") or []
        allowed_actions = context.get("allowed_actions") or []
        exception_types = [e.get("exception_type", "UNKNOWN") for e in exceptions]

        if not exception_types:
            return {
                "summary": "No linked exceptions were provided, so the root cause cannot be determined from evidence.",
                "exception_types": [],
                "root_cause_hypotheses": [],
                "root_cause": None,
                "evidence": [],
                "contradicting_evidence": [],
                "missing_information": ["Linked exception records"],
                "risk_assessment": {"level": "MEDIUM", "rationale": "Insufficient evidence to assess risk."},
                "suggested_resolutions": [],
                "required_actions": ["Link at least one exception before investigating."],
                "confidence": 0.0,
                "confidence_basis": "No evidence available.",
                "limitations": ["Stub provider: no semantic reasoning was performed."],
                "requires_human_review": True,
            }

        primary = exception_types[0]
        evidence = []
        for candidate in evidence_candidates[:4]:
            if not candidate.get("quote"):
                continue
            evidence.append(
                {
                    "source_type": candidate.get("source_type", "NOTE"),
                    "source_id": candidate.get("source_id"),
                    "document_id": candidate.get("document_id"),
                    "page_number": candidate.get("page_number"),
                    "field_name": candidate.get("field_name"),
                    "quote": candidate.get("quote"),
                    "relationship": candidate.get("relationship", "Referenced during investigation."),
                }
            )

        recommendations = []
        for action in allowed_actions[:2]:
            recommendations.append(
                {
                    "action_type": action,
                    "description": f"Stub recommendation for {primary.lower().replace('_', ' ')}.",
                    "rationale": "Derived from the exception types present in the case context.",
                    "risk_level": "MEDIUM",
                }
            )

        return {
            "summary": (
                f"Case {case.get('case_number', '')} contains {len(exception_types)} exception(s): "
                f"{', '.join(exception_types)}. Amount and document evidence were compared deterministically."
            ),
            "exception_types": exception_types,
            "root_cause_hypotheses": [
                {
                    "hypothesis": f"The {primary.lower().replace('_', ' ')} is caused by a data discrepancy "
                    "between the invoice and the matched purchase order.",
                    "likelihood": "medium",
                    "supporting_evidence_count": len(evidence),
                }
            ],
            "root_cause": f"{primary.replace('_', ' ').title()} confirmed by deterministic rules; "
            "root cause requires human confirmation.",
            "evidence": evidence,
            "contradicting_evidence": [],
            "missing_information": [] if len(evidence) >= 2 else ["Supporting document evidence"],
            "risk_assessment": {
                "level": "HIGH" if case.get("priority") in {"HIGH", "URGENT"} else "MEDIUM",
                "rationale": "Financial discrepancy affects payment accuracy.",
            },
            "suggested_resolutions": recommendations,
            "required_actions": ["Review the linked evidence and confirm the root cause."],
            "confidence": 0.55 if evidence else 0.2,
            "confidence_basis": "Heuristic stub score; not a calibrated probability.",
            "limitations": [
                "Stub provider: text was not semantically analysed.",
                "Evidence validation is performed separately by the deterministic validator.",
            ],
            "requires_human_review": True,
        }

    async def health(self) -> tuple[bool, str]:
        return True, "Deterministic stub provider (tests only)"


class StubEmbeddingProvider(EmbeddingProvider):
    name = "stub"

    def __init__(self, *_, dimensions: int = 384, model: str = "resolve-stub-embed") -> None:
        self.dimensions = dimensions
        self.model = model

    async def embed(self, texts: list[str], *, timeout: float = 60.0) -> EmbeddingResult:
        watch = Stopwatch()
        vectors = [self._vector(text) for text in texts]
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=self.model,
            dimensions=self.dimensions,
            input_tokens=sum(estimate_tokens(t) for t in texts),
            latency_ms=watch.elapsed_ms,
        )

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"[0-9a-zก-๙]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def health(self) -> tuple[bool, str]:
        return True, "Deterministic stub embeddings (tests only)"
