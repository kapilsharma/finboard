"""S3BlobStore against moto's in-process S3 (no network): it must behave like the local store
for everything the services rely on (ADR-0026). It lives with the integration tests because
the unit tests may not open the socket pair an event loop needs on Windows."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from finboard.core.config import Settings  # noqa: E402
from finboard.storage.blob import (  # noqa: E402
    BlobNotFound,
    BlobStore,
    LocalFsBlobStore,
    import_blob_key,
    user_prefix,
)
from finboard.storage.factory import build_blob_store  # noqa: E402
from finboard.storage.s3 import S3BlobStore  # noqa: E402

BUCKET = "finboard-test"


@pytest.fixture
def s3() -> Iterator[object]:
    with moto.mock_aws():
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="k", aws_secret_access_key="s"
        )
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture(params=["s3", "s3-prefixed", "local"])
def store(request: pytest.FixtureRequest, s3: object, tmp_path: Path) -> BlobStore:
    if request.param == "local":
        return LocalFsBlobStore(tmp_path)
    return S3BlobStore(s3, BUCKET, "tenant-a/blobs" if request.param == "s3-prefixed" else "")  # type: ignore[arg-type]


async def test_put_get_exists_delete(store: BlobStore) -> None:
    key = import_blob_key(uuid.uuid4(), uuid.uuid4())
    assert not await store.exists(key)
    with pytest.raises(BlobNotFound):
        await store.get(key)

    await store.put(key, b"%PDF-1.7 still encrypted")
    assert await store.exists(key)
    assert await store.get(key) == b"%PDF-1.7 still encrypted"
    await store.put(key, b"replaced")
    assert await store.get(key) == b"replaced"

    await store.delete(key)
    await store.delete(key)  # deleting what isn't there is fine
    assert not await store.exists(key)


async def test_delete_prefix_removes_one_users_files_only(store: BlobStore) -> None:
    alice, bob = uuid.uuid4(), uuid.uuid4()
    alices = [import_blob_key(alice, uuid.uuid4()) for _ in range(3)]
    bobs = import_blob_key(bob, uuid.uuid4())
    for key in (*alices, bobs):
        await store.put(key, b"x")

    assert await store.delete_prefix(user_prefix(alice)) == 3
    assert await store.delete_prefix(user_prefix(alice)) == 0
    assert not any([await store.exists(key) for key in alices])
    assert await store.get(bobs) == b"x"


@pytest.mark.parametrize("key", ["../escape", "/absolute", "users/../../x", "UPPER", "a b", ""])
async def test_keys_that_arent_generated_by_the_app_are_refused(store: BlobStore, key: str) -> None:
    with pytest.raises(ValueError, match="invalid blob key"):
        await store.put(key, b"x")


def test_a_prefix_keeps_two_installs_apart_in_one_bucket(s3: object) -> None:
    store = S3BlobStore(s3, BUCKET, "/tenant-a/blobs/")  # type: ignore[arg-type]
    assert store._key("users/u1/imports/i1") == "tenant-a/blobs/users/u1/imports/i1"


def test_factory_follows_the_settings(s3: object, tmp_path: Path) -> None:
    assert isinstance(build_blob_store(Settings(blob_dir=tmp_path)), LocalFsBlobStore)
    configured = build_blob_store(
        Settings(blob_backend="s3", s3_bucket=BUCKET, s3_region="us-east-1", s3_prefix="p")
    )
    assert isinstance(configured, S3BlobStore) and configured.prefix == "p"
    with pytest.raises(RuntimeError, match="FINBOARD_S3_BUCKET"):
        build_blob_store(Settings(blob_backend="s3"))
