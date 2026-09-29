"""Cliente de almacenamiento de objetos S3-compatible generico (Garage en dev,
S3 real en prod con las mismas env vars menos `S3_ENDPOINT_URL`). Ver infra/README.md."""

from __future__ import annotations

import os

import boto3
from botocore.client import BaseClient

_client: BaseClient | None = None


def get_object_store() -> BaseClient:
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
            # Garage valida la region de la firma SigV4 contra su `s3_region`
            # (docker/garage/garage.toml). S3 real usa una region real (us-east-1, etc).
            region_name=os.environ.get("S3_REGION", "us-east-1"),
            aws_access_key_id=os.environ["S3_ACCESS_KEY"],
            aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        )
    return _client
