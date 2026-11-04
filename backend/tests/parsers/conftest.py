import pytest


@pytest.fixture(autouse=True)
def _no_network(socket_disabled: None) -> None:
    """Parsers must never touch the network (pytest-socket raises if they try)."""
