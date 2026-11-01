import numpy as np
import pytest

from mindwars.concepts.library import Concept, ConceptLibrary


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

    def denied(*args, **kwargs):
        raise AssertionError("Tests must not open network connections or download weights")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
