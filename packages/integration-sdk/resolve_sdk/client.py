"""Small, dependency-light client for RESOLVE integrations."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx


class ResolveError(RuntimeError):
    def __init__(self, status_code: int, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class ResolveClient:
    """Bearer-token client scoped to one organization.

    The SDK stores no credentials on disk. Callers obtain tokens from their own secret store.
    """

    def __init__(
        self,
        base_url: str,
        *,
        access_token: str | None = None,
        organization_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.organization_id = organization_id
        self._client = httpx.Client(base_url=f"{self.base_url}/api/v1", timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ResolveClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.organization_id:
            headers["X-Organization-Id"] = self.organization_id
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, headers=self._headers(), **kwargs)
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
            except ValueError:
                error = {}
            raise ResolveError(
                response.status_code, error.get("message", response.text[:300]), error.get("code")
            )
        if response.status_code == 204:
            return None
        return response.json()

    def login(self, email: str, password: str, organization_slug: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"email": email, "password": password}
        if organization_slug:
            payload["organization_slug"] = organization_slug
        response = self._client.post("/auth/login", json=payload)
        if response.status_code >= 400:
            raise ResolveError(response.status_code, response.text[:300])
        result = response.json()
        self.access_token = result["access_token"]
        self.organization_id = result["organization"]["id"]
        return result

    def list_cases(self, *, status: str | None = None, page_size: int = 25) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": page_size}
        if status:
            params["status"] = status
        return self._request("GET", "/cases", params=params)

    def get_case(self, case_id: str) -> dict[str, Any]:
        return self._request("GET", f"/cases/{case_id}")

    def create_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/invoices", json=payload)

    def upload_document(self, path: str, *, filename: str, document_type: str = "INVOICE") -> dict[str, Any]:
        with open(path, "rb") as handle:
            files = {"file": (filename, handle, "application/octet-stream")}
            return self._request("POST", "/documents", files=files, data={"document_type": document_type})

    def get_analytics(self, days: int = 30) -> dict[str, Any]:
        return self._request("GET", "/analytics/overview", params={"days": days})


def inbound_webhook_signature(body: bytes, secret: str) -> str:
    """HMAC-SHA256 signature expected by RESOLVE's inbound webhook receiver."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_inbound_webhook(body: bytes, secret: str, signature: str) -> bool:
    return hmac.compare_digest(inbound_webhook_signature(body, secret), signature)


__all__ = ["ResolveClient", "ResolveError", "inbound_webhook_signature", "verify_inbound_webhook"]