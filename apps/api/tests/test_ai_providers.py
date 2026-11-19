"""Real HTTP tests of the OpenAI-compatible provider against a local fake server.

No external credentials are used: the fake server reproduces the parts of the
OpenAI wire protocol the application depends on (chat completions, embeddings,
model listing, rate limiting and error shapes).
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from pydantic import BaseModel

from app.ai.base import ChatMessage, ProviderError
from app.ai.client import structured_completion
from app.ai.openai_provider import OpenAICompatibleEmbeddings, OpenAICompatibleProvider
from app.config.settings import settings
from app.core.errors import AIOutputError, AIUnavailableError


class Answer(BaseModel):
    answer: str
    confidence: float


class FakeOpenAI:
    def __init__(self) -> None:
        self.chat_script: list[tuple[int, dict[str, Any]]] = []
        self.embedding_script: list[tuple[int, dict[str, Any]]] = []
        self.requests: list[dict[str, Any]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _handler(self):  # noqa: ANN202 - closure
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # noqa: ANN002
                return

            def _send(self, status: int, body: dict[str, Any]) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:  # noqa: N802
                fake.requests.append({"method": "GET", "path": self.path})
                if self.path.endswith("/models"):
                    self._send(200, {"data": [{"id": "fake-model"}]})
                else:
                    self._send(404, {"error": {"message": "not found"}})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "body": body,
                        "authorization": self.headers.get("Authorization"),
                    }
                )
                if self.path.endswith("/chat/completions"):
                    status, response = (
                        fake.chat_script.pop(0)
                        if fake.chat_script
                        else (200, {"choices": [{"message": {"content": json.dumps({"answer": "ok", "confidence": 0.9})}}]})
                    )
                    self._send(status, response)
                    return
                if self.path.endswith("/embeddings"):
                    status, response = (
                        fake.embedding_script.pop(0)
                        if fake.embedding_script
                        else (200, {"data": [{"embedding": [0.1, 0.2, 0.3]}], "model": "fake-embed"})
                    )
                    self._send(status, response)
                    return
                self._send(404, {"error": {"message": "not found"}})

        return Handler


@pytest.fixture()
def fake_openai():
    fake = FakeOpenAI()
    try:
        yield fake
    finally:
        fake.close()


def _provider(fake: FakeOpenAI) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(base_url=fake.base_url, api_key="test-key", model="fake-model")


def test_chat_completion_round_trip(fake_openai: FakeOpenAI) -> None:
    provider = _provider(fake_openai)
    result = asyncio.run(
        provider.complete([ChatMessage(role="user", content="hello")], json_mode=True)
    )
    assert result.provider == "openai"
    assert json.loads(result.content)["answer"] == "ok"
    assert result.input_tokens > 0
    assert fake_openai.requests[0]["authorization"] == "Bearer test-key"
    assert fake_openai.requests[0]["body"]["response_format"] == {"type": "json_object"}


def test_rate_limit_is_retried_then_succeeds(fake_openai: FakeOpenAI) -> None:
    fake_openai.chat_script = [
        (429, {"error": {"message": "slow down"}}),
        (200, {"choices": [{"message": {"content": json.dumps({"answer": "recovered", "confidence": 0.8})}}]}),
    ]
    provider = _provider(fake_openai)
    parsed, result, attempts = asyncio.run(
        structured_completion(
            provider=provider,
            messages=[ChatMessage(role="user", content="return json")],
            schema=Answer,
            max_attempts=3,
        )
    )
    assert attempts == 2
    assert parsed.answer == "recovered"
    assert len(fake_openai.requests) == 2


def test_invalid_json_triggers_repair_attempt(fake_openai: FakeOpenAI) -> None:
    fake_openai.chat_script = [
        (200, {"choices": [{"message": {"content": "not json at all"}}]}),
        (200, {"choices": [{"message": {"content": json.dumps({"answer": "fixed", "confidence": 1.0})}}]}),
    ]
    provider = _provider(fake_openai)
    parsed, _result, attempts = asyncio.run(
        structured_completion(
            provider=provider,
            messages=[ChatMessage(role="user", content="return json")],
            schema=Answer,
            max_attempts=2,
        )
    )
    assert attempts == 2
    assert parsed.answer == "fixed"
    repair_messages = fake_openai.requests[1]["body"]["messages"]
    assert repair_messages[-1]["role"] == "user"
    assert "could not be accepted" in repair_messages[-1]["content"]


def test_persistent_server_error_raises_unavailable(fake_openai: FakeOpenAI) -> None:
    fake_openai.chat_script = [
        (500, {"error": {"message": "boom"}}),
        (500, {"error": {"message": "boom"}}),
    ]
    provider = _provider(fake_openai)
    with pytest.raises(AIUnavailableError):
        asyncio.run(
            structured_completion(
                provider=provider,
                messages=[ChatMessage(role="user", content="return json")],
                schema=Answer,
                max_attempts=2,
            )
        )
    assert len(fake_openai.requests) == 2


def test_client_error_is_not_retried(fake_openai: FakeOpenAI) -> None:
    fake_openai.chat_script = [(400, {"error": {"message": "bad request"}})]
    provider = _provider(fake_openai)
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.complete([ChatMessage(role="user", content="x")]))
    assert excinfo.value.retryable is False
    assert len(fake_openai.requests) == 1


def test_schema_validation_failure_exhausts_retries(fake_openai: FakeOpenAI) -> None:
    fake_openai.chat_script = [
        (200, {"choices": [{"message": {"content": json.dumps({"answer": "x"})}}]}),
        (200, {"choices": [{"message": {"content": json.dumps({"answer": "x"})}}]}),
    ]
    provider = _provider(fake_openai)
    with pytest.raises(AIOutputError):
        asyncio.run(
            structured_completion(
                provider=provider,
                messages=[ChatMessage(role="user", content="json")],
                schema=Answer,
                max_attempts=2,
            )
        )


def test_embeddings_and_health(fake_openai: FakeOpenAI) -> None:
    embeddings = OpenAICompatibleEmbeddings(
        base_url=fake_openai.base_url, api_key="test-key", model="fake-embed", dimensions=3
    )
    result = asyncio.run(embeddings.embed(["one", "two"]))
    assert result.vectors == [[0.1, 0.2, 0.3]]
    assert result.dimensions == 3

    provider = _provider(fake_openai)
    healthy, detail = asyncio.run(provider.health())
    assert healthy is True
    assert "fake-model" in detail


def test_registry_requires_credentials_and_builds_real_provider(monkeypatch) -> None:
    from app.ai import registry

    monkeypatch.setattr(settings, "AI_PROVIDER", "openai")
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    assert registry.build_llm_provider() is None

    monkeypatch.setattr(settings, "AI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "AI_BASE_URL", "http://127.0.0.1:9/v1")
    provider = registry.build_llm_provider()
    assert provider is not None
    assert provider.name == "openai"
    assert provider.api_key == "test-key"
