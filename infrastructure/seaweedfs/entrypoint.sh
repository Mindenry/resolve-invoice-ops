#!/bin/sh
# Generate a SeaweedFS S3 identity from the environment, then start a single-node
# master + volume + filer + S3 gateway. Credentials are required: without an
# identity file SeaweedFS would allow anonymous access.
set -eu

if [ -z "${S3_ACCESS_KEY:-}" ] || [ -z "${S3_SECRET_KEY:-}" ]; then
  echo "S3_ACCESS_KEY and S3_SECRET_KEY must be set for the S3 gateway." >&2
  exit 1
fi

CONFIG=/tmp/seaweedfs-s3.json
umask 077
cat > "$CONFIG" <<EOF
{
  "identities": [
    {
      "name": "resolve",
      "credentials": [
        {"accessKey": "${S3_ACCESS_KEY}", "secretKey": "${S3_SECRET_KEY}"}
      ],
      "actions": ["Admin", "Read", "Write", "List", "Tagging"]
    }
  ]
}
EOF

exec weed server \
  -dir=/data \
  -master.port=9333 \
  -master.volumeSizeLimitMB=1024 \
  -volume.port=8080 \
  -volume.max=64 \
  -filer.port=8888 \
  -s3 \
  -s3.port=8333 \
  -s3.config="$CONFIG"
