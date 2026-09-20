import json

from app.embeddings.providers import MockEmbeddingProvider, OpenAICompatibleEmbeddingProvider
from app.llm.providers import MockLLMProvider, OpenAICompatibleProvider
from app.domain.models import RetrievalEvidence


def test_mock_embedding_is_deterministic_and_normalized() -> None:
    provider = MockEmbeddingProvider()
    first = provider.embed("UART 初始化 PA9")
    second = provider.embed("UART 初始化 PA9")
    assert first == second
    assert len(first) == provider.dimension
    assert 0.99 < sum(value * value for value in first) ** 0.5 < 1.01


def test_mock_llm_refuses_without_evidence() -> None:
    assert MockLLMProvider().generate("irrelevant", []) == "现有资料不足以确定。"


def test_mock_llm_quotes_chunk_ids() -> None:
    evidence = [
        RetrievalEvidence(
            chunk_id="chunk-1",
            content="PA9 是 TX 引脚。",
            source_file="uart.md",
            relative_path="uart.md",
            document_type="md",
            score=0.8,
        )
    ]
    answer = MockLLMProvider().generate("question", evidence)
    assert "chunk-1" in answer
    assert "PA9" in answer


def test_openai_compatible_providers_use_fake_transport(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert timeout > 0
        assert request.headers["Authorization"] == "Bearer test-key"
        if request.full_url.endswith("/embeddings"):
            return FakeResponse({"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
        return FakeResponse({"choices": [{"message": {"content": "grounded"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    embedding = OpenAICompatibleEmbeddingProvider(
        "http://local-fake/v1", "test-key", "embed", dimension=2
    )
    llm = OpenAICompatibleProvider("http://local-fake/v1", "test-key", "chat")
    assert embedding.embed("text") == [1.0, 0.0]
    assert llm.generate("prompt", []) == "grounded"


def test_mimo_endpoint_payload_uses_documented_controls(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.headers)
        seen["payload"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        "https://api.xiaomimimo.com/v1", "test-key", "mimo-v2.5-pro"
    )
    assert provider.generate("synthetic prompt", []) == "ok"
    assert seen["url"] == "https://api.xiaomimimo.com/v1/chat/completions"
    payload = seen["payload"]
    assert payload["model"] == "mimo-v2.5-pro"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_completion_tokens"] == 1024
    assert payload["stream"] is False
