"""Blobs in an S3-compatible object store (ADR-0026, server mode).

Needs the optional `s3` extra (boto3). boto3 is synchronous, so each call runs in a thread.
Keys are the same application-generated keys the local store uses, under an optional prefix.
The bucket's own settings decide encryption at rest and versioning; statements are stored
exactly as uploaded (still bank-encrypted).
"""

import asyncio
from typing import TYPE_CHECKING, Any

from finboard.storage.blob import BlobNotFound, validate_key

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

_MISSING = {"404", "NoSuchKey", "NotFound"}


class S3Unavailable(RuntimeError):
    pass


def make_client(
    *,
    endpoint_url: str | None,
    region: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
) -> "S3Client":
    try:
        import boto3
    except ImportError as exc:
        raise S3Unavailable(
            "FINBOARD_BLOB_BACKEND=s3 needs the s3 extra: uv sync --extra s3"
        ) from exc
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


def _is_missing(exc: Exception) -> bool:
    response: dict[str, Any] = getattr(exc, "response", None) or {}
    return str(response.get("Error", {}).get("Code")) in _MISSING


class S3BlobStore:
    def __init__(self, client: "S3Client", bucket: str, prefix: str = "") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        validate_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=self._key(key), Body=data
        )

    def _get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()
        except ClientError as exc:
            if _is_missing(exc):
                raise BlobNotFound(key) from exc
            raise

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=self._key(key))

    def _exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as exc:
            if _is_missing(exc):
                return False
            raise
        return True

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._exists, key)

    def _delete_prefix(self, prefix: str) -> int:
        # The trailing slash keeps `users/<id>` from also matching `users/<id>0…`.
        full = self._key(prefix) + "/"
        deleted = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full):
            keys: list[ObjectIdentifierTypeDef] = [
                {"Key": item["Key"]} for item in page.get("Contents", [])
            ]
            if keys:  # a page holds at most 1,000 keys, the limit of one delete request
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
                deleted += len(keys)
        return deleted

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every blob under `prefix` (one user's files). Returns how many."""
        return await asyncio.to_thread(self._delete_prefix, prefix)
