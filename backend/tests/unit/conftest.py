import pytest


@pytest.fixture(autouse=True)
def _no_network(socket_disabled: None) -> None:
    """Unit tests are pure: pytest-socket fails any test that opens a socket."""
