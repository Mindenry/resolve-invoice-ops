"""S3 compatibility tests for the storage backend and the sync helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import settings
from app.core.errors import StorageError
from app.scripts.s3_sync import download, upload
from app.services.storage import S3Storage


class FakeS3Client:
    def __init__(self, *, head_failures: int = 0, create_error: Exception | None = None) -> None:
        self.head_failures = head_failures
        self.create_error = create_error
        self.head_calls = 0
        self.created: list[str] = []
        self.uploaded: list[tuple[str, str, str]] = []
        self.deleted: list[str] = []
        self.remote: set[str] = set()

    def head_bucket(self, **kwargs):
        self.head_calls += 1
        if self.head_calls <= self.head_failures:
            raise RuntimeError("not found")
        return {}

    def create_bucket(self, **kwargs):
        self.created.append(kwargs["Bucket"])
        if self.create_error:
            raise self.create_error
        return {}

    def upload_file(self, filename, bucket, key):
        self.uploaded.append((filename, bucket, key))

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        self.remote.discard(Key)

    def download_file(self, bucket, key, filename):
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).write_text(f"content:{key}")

    def get_paginator(self, name):
        assert name == "list_objects_v2"

        client = self

        class Paginator:
            def paginate(self, Bucket, Prefix=""):
                yield {"Contents": [{"Key": key} for key in sorted(client.remote)]}

        return Paginator()


def _configure(monkeypatch, **overrides) -> None:
    values = {
        "S3_ACCESS_KEY": "test-key",
        "S3_SECRET_KEY": "test-secret",
        "S3_ENDPOINT_URL": "http://seaweedfs:8333",
        "S3_BUCKET": "resolve-documents",
        "S3_REGION": "us-east-1",
        "S3_USE_SSL": False,
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)


def test_s3_storage_uses_path_style_for_custom_endpoint(monkeypatch) -> None:
    _configure(monkeypatch)
    captured: dict[str, object] = {}
    fake = FakeS3Client()

    def fake_client(service, **kwargs):
        captured.update(kwargs)
        return fake

    import boto3

    monkeypatch.setattr(boto3, "client", fake_client)
    storage = S3Storage()

    assert storage.name == "s3"
    assert captured["config"].s3["addressing_style"] == "path"
    assert captured["config"].signature_version == "s3v4"
    assert fake.head_calls == 1


def test_s3_storage_uses_virtual_host_style_for_aws(monkeypatch) -> None:
    _configure(monkeypatch, S3_ENDPOINT_URL="")
    captured: dict[str, object] = {}
    fake = FakeS3Client()

    import boto3

    monkeypatch.setattr(boto3, "client", lambda service, **kwargs: (captured.update(kwargs), fake)[1])
    S3Storage()

    assert captured["config"].s3["addressing_style"] == "virtual"


def test_s3_storage_tolerates_concurrent_bucket_creation(monkeypatch) -> None:
    _configure(monkeypatch)
    fake = FakeS3Client(head_failures=1, create_error=RuntimeError("BucketAlreadyOwnedByYou"))

    import boto3

    monkeypatch.setattr(boto3, "client", lambda service, **kwargs: fake)

    S3Storage()  # the second HEAD confirms the bucket exists
    assert fake.head_calls == 2


def test_s3_storage_raises_when_bucket_cannot_be_created(monkeypatch) -> None:
    _configure(monkeypatch)
    fake = FakeS3Client(head_failures=99, create_error=RuntimeError("denied"))

    import boto3

    monkeypatch.setattr(boto3, "client", lambda service, **kwargs: fake)

    with pytest.raises(StorageError):
        S3Storage()


def test_s3_sync_upload_prefixes_keys_and_deletes_stale(tmp_path: Path) -> None:
    source = tmp_path / "documents"
    (source / "org").mkdir(parents=True)
    (source / "org" / "invoice.pdf").write_bytes(b"pdf")
    (source / "readme.txt").write_text("hello")
    fake = FakeS3Client()
    fake.remote.update({"resolve/old.pdf", "resolve/org/invoice.pdf"})

    count = upload(
        fake, "resolve-documents", source, "resolve", create=True, delete=True
    )

    assert count == 2
    assert ("resolve/readme.txt" in [key for _, _, key in fake.uploaded])
    assert ("resolve/org/invoice.pdf" in [key for _, _, key in fake.uploaded])
    assert fake.deleted == ["resolve/old.pdf"]


def test_s3_sync_download_rejects_path_traversal(tmp_path: Path) -> None:
    fake = FakeS3Client()
    fake.remote.add("../escape.txt")

    with pytest.raises(SystemExit):
        download(fake, "resolve-documents", tmp_path / "restore", "", delete=False)


def test_s3_sync_download_writes_nested_files(tmp_path: Path) -> None:
    fake = FakeS3Client()
    fake.remote.update({"org/invoice.pdf", "org/nested/note.txt"})
    target = tmp_path / "restore"

    count = download(fake, "resolve-documents", target, "", delete=False)

    assert count == 2
    assert (target / "org" / "invoice.pdf").exists()
    assert (target / "org" / "nested" / "note.txt").exists()
