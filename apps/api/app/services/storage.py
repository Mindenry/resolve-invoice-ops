"""Document storage abstraction with local filesystem and S3-compatible backends."""

from __future__ import annotations

import contextlib
import hashlib
import shutil
from pathlib import Path
from typing import Protocol

from app.config.settings import settings
from app.core.errors import StorageError
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageBackend(Protocol):
    name: str

    def save(self, key: str, data: bytes) -> None: ...

    def read(self, key: str) -> bytes: ...

    def open_stream(self, key: str): ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def health(self) -> tuple[bool, str]: ...


def _safe_key(key: str) -> str:
    normalized = key.replace("\\", "/").lstrip("/")
    if ".." in normalized.split("/"):
        raise StorageError("Invalid storage key.", code="invalid_storage_key")
    return normalized


class LocalStorage:
    name = "local"

    def __init__(self, base_dir: str | None = None) -> None:
        self.base = Path(base_dir or settings.STORAGE_LOCAL_DIR).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.base / _safe_key(key)).resolve()
        if not str(path).startswith(str(self.base)):
            raise StorageError("Invalid storage key.", code="invalid_storage_key")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StorageError("Stored object does not exist.", code="object_not_found")
        return path.read_bytes()

    def open_stream(self, key: str):
        path = self._path(key)
        if not path.exists():
            raise StorageError("Stored object does not exist.", code="object_not_found")
        return path.open("rb")

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def health(self) -> tuple[bool, str]:
        try:
            probe = self.base / ".health"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True, f"local storage writable at {self.base}"
        except OSError as exc:
            return False, str(exc)


class S3Storage:
    name = "s3"

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        if not settings.S3_ACCESS_KEY or not settings.S3_SECRET_KEY:
            raise StorageError("S3 credentials are not configured.", code="storage_not_configured")
        self.bucket = settings.S3_BUCKET
        # Custom endpoints (SeaweedFS, MinIO, R2) generally do not provide
        # per-bucket DNS, so use path-style addressing there. Managed AWS S3
        # keeps the modern virtual-hosted style.
        addressing_style = "path" if settings.S3_ENDPOINT_URL else "virtual"
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            use_ssl=settings.S3_USE_SSL,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": addressing_style},
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        with contextlib.suppress(Exception):  # boto3 raises client-specific errors
            self.client.head_bucket(Bucket=self.bucket)
            return
        try:
            self.client.create_bucket(Bucket=self.bucket)
        except Exception as exc:  # noqa: BLE001
            # Another API/worker process may have created the bucket between
            # our HEAD and CREATE calls. Confirm before failing readiness.
            try:
                self.client.head_bucket(Bucket=self.bucket)
                return
            except Exception:  # noqa: BLE001
                raise StorageError(
                    f"Could not access bucket: {exc}", code="storage_unavailable"
                ) from exc

    def save(self, key: str, data: bytes) -> None:
        try:
            self.client.put_object(Bucket=self.bucket, Key=_safe_key(key), Body=data)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Upload to object storage failed: {exc}", code="storage_write_failed") from exc

    def read(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=_safe_key(key))
            return response["Body"].read()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Read from object storage failed: {exc}", code="storage_read_failed") from exc

    def open_stream(self, key: str):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=_safe_key(key))
            return response["Body"]
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Read from object storage failed: {exc}", code="storage_read_failed") from exc

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=_safe_key(key))
        except Exception as exc:  # noqa: BLE001
            logger.warning("s3_delete_failed", key=key, error=str(exc))

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))
            return True
        except Exception:  # noqa: BLE001
            return False

    def health(self) -> tuple[bool, str]:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True, f"S3 bucket '{self.bucket}' reachable"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is not None:
        return _backend
    _backend = S3Storage() if settings.STORAGE_BACKEND == "s3" else LocalStorage()
    return _backend


def reset_storage_cache() -> None:
    global _backend
    _backend = None


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def storage_key(org_id: str, sha256: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower()[:10]
    return f"{org_id}/{sha256[:2]}/{sha256}{suffix}"


def copy_file_to(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
