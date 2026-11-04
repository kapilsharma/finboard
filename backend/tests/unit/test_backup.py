"""Pre-migration backup (ARCHITECTURE §16): pg_dump with the password in the environment."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from finboard.db import migrate

URL = "postgresql+asyncpg://finboard_owner:s3cret-pw@db.local:55432/finboard"


def test_backup_runs_pg_dump_without_the_password_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(
        args: list[str], *, env: dict[str, str], **_: Any
    ) -> subprocess.CompletedProcess[str]:
        seen["args"], seen["env"] = args, env
        Path(next(a for a in args if a.startswith("--file=")).split("=", 1)[1]).write_bytes(b"dump")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(migrate.shutil, "which", lambda _: "/usr/bin/pg_dump")
    monkeypatch.setattr(migrate.subprocess, "run", fake_run)
    target = migrate.backup(URL, tmp_path / "backups", revision="abc123")
    assert target is not None and target.exists() and target.name.startswith("finboard-")
    assert target.name.endswith("-abc123.dump")
    assert not any("s3cret-pw" in a for a in seen["args"])
    assert seen["env"]["PGPASSWORD"] == "s3cret-pw"
    assert "--format=custom" in seen["args"] and "--host=db.local" in seen["args"]
    assert oct(target.stat().st_mode & 0o777) in ("0o600", "0o666")  # 0600 where supported


def test_missing_pg_dump_is_a_warning_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(migrate.shutil, "which", lambda _: None)
    assert migrate.backup(URL, tmp_path) is None


def test_a_failed_dump_stops_the_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrate.shutil, "which", lambda _: "/usr/bin/pg_dump")
    monkeypatch.setattr(
        migrate.subprocess,
        "run",
        lambda args, **_: subprocess.CompletedProcess(
            args, 1, "", "pg_dump: error: server version mismatch"
        ),
    )
    with pytest.raises(migrate.BackupFailed, match="server version mismatch"):
        migrate.backup(URL, tmp_path)
    assert list(tmp_path.glob("*.dump")) == []


def test_only_an_older_schema_needs_a_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrate, "head_revision", lambda: "head")
    for current, expected in ((None, False), ("head", False), ("older", True)):
        monkeypatch.setattr(migrate, "current_revision", lambda _url, c=current: c)
        assert migrate.needs_backup(URL) is expected
