import socket

import pytest
import pytest_socket


def test_network_sockets_stay_blocked() -> None:
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
