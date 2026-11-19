"""Verify a restored S3 bucket object against the local backup mirror (SHA-256)."""

from __future__ import annotations

import hashlib
import os
import sys

import boto3
from botocore.config import Config

key = sys.argv[1]
local_root = sys.argv[2]
bucket = sys.argv[3]

endpoint = os.environ.get("S3_ENDPOINT_URL", "http://seaweedfs:8333")
client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name=os.environ.get("S3_REGION", "us-east-1"),
    config=Config(s3={"addressing_style": "path"}),
)
body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
remote_sha = hashlib.sha256(body).hexdigest()

local_path = os.path.join(local_root, key.replace("/", os.sep))
with open(local_path, "rb") as fh:
    local_sha = hashlib.sha256(fh.read()).hexdigest()

print("remote_sha256", remote_sha)
print("local_sha256 ", local_sha)
print("bytes", len(body))
print("MATCH" if remote_sha == local_sha else "MISMATCH")
sys.exit(0 if remote_sha == local_sha else 1)
