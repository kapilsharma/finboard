"""Test configuration. Integration tests use the `finboard_test` database of the dev compose stack
(deploy/compose.dev.yaml); CI provides the same via service containers."""

import json
import os
import tempfile

_TEST_DB = "postgresql+asyncpg://{role}:{role}_dev@127.0.0.1:55432/finboard_test"

os.environ.setdefault("FINBOARD_DATABASE_URL", _TEST_DB.format(role="finboard_app"))
os.environ.setdefault("FINBOARD_MIGRATION_DATABASE_URL", _TEST_DB.format(role="finboard_owner"))
os.environ.setdefault("FINBOARD_REDIS_URL", "redis://127.0.0.1:56379/15")
os.environ["FINBOARD_ENV"] = "test"
os.environ["FINBOARD_LOG_JSON"] = "false"
os.environ["FINBOARD_LOG_LEVEL"] = "WARNING"
# Imports: a throwaway blob directory and secret key, plus the test-only parsers.
os.environ.setdefault("FINBOARD_BLOB_DIR", tempfile.mkdtemp(prefix="finboard-test-blobs-"))
os.environ.setdefault("FINBOARD_SECRET_KEY", "test-only-secret-key")
os.environ["FINBOARD_EXTRA_PARSERS"] = json.dumps(
    [
        "tests.integration.fake_parsers:MismatchParser",
        "tests.integration.fake_parsers:SoftTimeoutParser",
        "tests.integration.fake_parsers:HangingParser",
        "tests.integration.fake_parsers:OptionsParser",
    ]
)

# The integration suite truncates tables. Never let it near a real database.
for _var in ("FINBOARD_DATABASE_URL", "FINBOARD_MIGRATION_DATABASE_URL"):
    if not os.environ[_var].rsplit("/", 1)[-1].endswith("_test"):
        raise RuntimeError(f"{_var} must point at a database whose name ends in '_test'")
