from pathlib import Path

import pytest

from finboard import cli
from finboard.parsers.builtin.generic_table.fixtures import GenericTableFixtures


def test_init_writes_a_secret_key_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINBOARD_SECRET_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("FINBOARD_LOG_LEVEL=DEBUG", encoding="utf-8")
    assert cli.init_secret_key(env) is True
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "FINBOARD_LOG_LEVEL=DEBUG"
    assert lines[1].startswith("FINBOARD_SECRET_KEY=") and len(lines[1]) > 40
    assert cli.init_secret_key(env) is False
    assert env.read_text(encoding="utf-8").splitlines() == lines


def test_init_respects_an_existing_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FINBOARD_SECRET_KEY", "from-a-secrets-manager")
    assert cli.init_secret_key(tmp_path / ".env") is False
    assert not (tmp_path / ".env").exists()


def test_inspect_layout_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data, statement = GenericTableFixtures().build(1, 5)
    pdf = tmp_path / "my-salary-statement.pdf"
    pdf.write_bytes(data)
    cli.main(["inspect-layout", str(pdf)])
    out = capsys.readouterr().out
    assert "=== page 1" in out
    assert "salary" not in out.lower()  # not even the file name
    assert statement.transactions[0].description not in out


def test_inspect_layout_refuses_encrypted_without_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, _ = GenericTableFixtures().build(1, 2, encrypted_with="pw")
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(data)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit, match="password-protected"):
        cli.main(["inspect-layout", str(pdf)])
