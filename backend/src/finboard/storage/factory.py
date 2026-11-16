"""The blob store this configuration asks for. The API and the workers both build theirs here,
so they always agree on where statements live."""

from finboard.core.config import Settings
from finboard.storage.blob import BlobStore, LocalFsBlobStore


def build_blob_store(settings: Settings) -> BlobStore:
    if settings.blob_backend == "local":
        return LocalFsBlobStore(settings.blob_dir)
    from finboard.storage.s3 import S3BlobStore, make_client

    if not settings.s3_bucket:
        raise RuntimeError("FINBOARD_BLOB_BACKEND=s3 needs FINBOARD_S3_BUCKET")
    secret = settings.s3_secret_access_key
    # Empty strings (an unset variable passed through compose) mean "not set".
    client = make_client(
        endpoint_url=settings.s3_endpoint_url or None,
        region=settings.s3_region or None,
        access_key_id=settings.s3_access_key_id or None,
        secret_access_key=secret.get_secret_value() if secret else None,
    )
    return S3BlobStore(client, settings.s3_bucket, settings.s3_prefix)
