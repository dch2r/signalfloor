import pytest

from signalfloor_agent.testing import HashingEmbedder


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()
