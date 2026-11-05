from collections.abc import Iterator

import pytest
import pytest_socket


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    """Unit tests are pure: pytest-socket fails any test that opens a network socket. Unix
    sockets stay allowed, because an asyncio event loop needs a local socketpair."""
    pytest_socket.disable_socket(allow_unix_socket=True)
    yield
    pytest_socket.enable_socket()
