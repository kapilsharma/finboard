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


def test_init_compose_writes_the_passwords_and_never_replaces_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FINBOARD_SECRET_KEY", raising=False)
    env = tmp_path / ".env"
    names = ["FINBOARD_SECRET_KEY", *cli.COMPOSE_PASSWORDS]
    assert cli.init_compose_env(env) == names
    values = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines())
    assert list(values) == names
    # Hex only: safe inside a database URL and the SQL of the Postgres init script.
    assert all(len(values[n]) == 48 and values[n].isalnum() for n in cli.COMPOSE_PASSWORDS)
    assert len({values[n] for n in cli.COMPOSE_PASSWORDS}) == 3

    # The passwords are fixed in Postgres when its volume is created: a rerun changes nothing.
    assert cli.init_compose_env(env) == []
    assert dict(line.split("=", 1) for line in env.read_text("utf-8").splitlines()) == values


def test_init_compose_completes_a_file_that_only_has_the_secret_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FINBOARD_SECRET_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("FINBOARD_SECRET_KEY=keep-me\nFINBOARD_AI_ASK=gemini", encoding="utf-8")
    assert cli.init_compose_env(env) == list(cli.COMPOSE_PASSWORDS)
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["FINBOARD_SECRET_KEY=keep-me", "FINBOARD_AI_ASK=gemini"]
    assert len(lines) == 5


def test_serve_in_prod_refuses_to_start_without_a_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from finboard.core.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(env="prod", secret_key=None))
    monkeypatch.setattr(cli, "_migrate", lambda **_: pytest.fail("must not migrate"))
    with pytest.raises(SystemExit, match="FINBOARD_SECRET_KEY is not set"):
        cli.main(["serve"])


def test_swagger_ui_is_a_development_tool_only() -> None:
    # Swagger UI loads its assets from a CDN; the packaged app makes no outbound requests.
    from finboard.core.config import Settings
    from finboard.main import create_app

    assert create_app(Settings(env="prod")).docs_url is None
    assert create_app(Settings(env="dev")).docs_url == "/api/docs"
