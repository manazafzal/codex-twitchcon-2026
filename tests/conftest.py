import numpy as np
import pytest

from nous.concepts.library import Concept, ConceptLibrary


@pytest.fixture
def library():
    return ConceptLibrary(
        [
            Concept("ocean", "Ocean", 0, ("sea",)),
            Concept("space", "Space", 1, ("star",)),
            Concept("jazz", "Jazz", 2, ("sax",)),
        ],
        np.eye(32)[:3],
        np.eye(32)[:3],
        np.zeros(32),
        np.full(3, 0.1),
        {"model": "mock"},
    )


@pytest.fixture(autouse=True)
def no_test_network(monkeypatch):
    import socket

    connect = socket.socket.connect

    def denied(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return connect(sock, address)
        raise AssertionError("Tests allow only loopback connections; no downloads")

    monkeypatch.setattr(socket.socket, "connect", denied)
