import pytest
from memory.embeddings import EmbeddingClient


def test_init_defaults():
    client = EmbeddingClient()
    assert "11434" in client.base_url
    assert client.model == "qwen3-embedding:0.6b"
    assert client.dim == 1024


def test_init_custom():
    client = EmbeddingClient(
        base_url="http://localhost:9999",
        model="custom-model",
        dim=512,
    )
    assert client.base_url == "http://localhost:9999"
    assert client.model == "custom-model"
    assert client.dim == 512
