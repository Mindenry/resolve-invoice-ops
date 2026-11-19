"""Mirror a local directory to or from an S3-compatible bucket.

Used by the Compose backup/restore scripts so they use the same boto3 client
configuration as the application (path-style addressing, explicit credentials).
The AWS CLI v2 is intentionally not required: some S3-compatible servers reject
its streaming-checksum uploads.

Usage (inside the api container):
    python -m app.scripts.s3_sync download --bucket resolve-documents --dest /backup
    python -m app.scripts.s3_sync upload --bucket resolve-documents-restore --source /backup --create-bucket
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config.settings import settings


def _client():
    import boto3
    from botocore.config import Config

    addressing_style = "path" if settings.S3_ENDPOINT_URL else "virtual"
    return boto3.client(
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
            read_timeout=60,
            retries={"max_attempts": 5, "mode": "standard"},
            max_pool_connections=4,
        ),
    )


def _ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:  # noqa: BLE001 - create when missing
        client.create_bucket(Bucket=bucket)


def _remote_keys(client, bucket: str, prefix: str) -> set[str]:
    keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            keys.add(item["Key"])
    return keys


def upload(client, bucket: str, source: Path, prefix: str, *, create: bool, delete: bool) -> int:
    if create:
        _ensure_bucket(client, bucket)
    source = source.resolve()
    if not source.is_dir():
        raise SystemExit(f"Source directory does not exist: {source}")
    uploaded = 0
    local_keys: set[str] = set()
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        key = f"{prefix.strip('/')}/{relative}".lstrip("/") if prefix.strip("/") else relative
        local_keys.add(key)
        client.upload_file(str(path), bucket, key)
        uploaded += 1
    if delete:
        for key in _remote_keys(client, bucket, prefix.strip("/")):
            if key not in local_keys:
                client.delete_object(Bucket=bucket, Key=key)
    return uploaded


def download(client, bucket: str, dest: Path, prefix: str, *, delete: bool) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    keys = _remote_keys(client, bucket, prefix.strip("/"))
    downloaded = 0
    for key in sorted(keys):
        relative = key[len(prefix.strip("/")) :].lstrip("/") if prefix.strip("/") else key
        if not relative:
            continue
        target = (dest / relative).resolve()
        if not target.is_relative_to(dest.resolve()):
            raise SystemExit(f"Refusing unsafe object key: {key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, key, str(target))
        downloaded += 1
    if delete:
        for path in sorted(dest.rglob("*"), reverse=True):
            if path.is_file():
                relative = path.relative_to(dest).as_posix()
                key = f"{prefix.strip('/')}/{relative}".lstrip("/") if prefix.strip("/") else relative
                if key not in keys:
                    path.unlink()
    return downloaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mirror a directory to/from S3.")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upload", help="Upload a local directory")
    up.add_argument("--bucket", required=True)
    up.add_argument("--source", required=True)
    up.add_argument("--prefix", default="")
    up.add_argument("--create-bucket", action="store_true")
    up.add_argument("--delete", action="store_true", help="Delete remote keys not present locally")

    down = sub.add_parser("download", help="Download a bucket prefix")
    down.add_argument("--bucket", required=True)
    down.add_argument("--dest", required=True)
    down.add_argument("--prefix", default="")
    down.add_argument("--delete", action="store_true", help="Delete local files not present remotely")

    args = parser.parse_args(argv)
    if not settings.S3_ACCESS_KEY or not settings.S3_SECRET_KEY:
        print("S3 credentials are not configured.", file=sys.stderr)
        return 2
    client = _client()
    if args.command == "upload":
        count = upload(
            client,
            args.bucket,
            Path(args.source),
            args.prefix,
            create=args.create_bucket,
            delete=args.delete,
        )
        print(f"Uploaded {count} object(s) to s3://{args.bucket}/{args.prefix}".rstrip("/"))
    else:
        count = download(client, args.bucket, Path(args.dest), args.prefix, delete=args.delete)
        print(f"Downloaded {count} object(s) from s3://{args.bucket}/{args.prefix}".rstrip("/"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
