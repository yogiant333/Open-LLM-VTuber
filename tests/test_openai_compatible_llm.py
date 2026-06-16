import pytest

from src.open_llm_vtuber.agent.stateless_llm.openai_compatible_llm import AsyncLLM


class _EmptyAsyncStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def close(self):
        pass


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return _EmptyAsyncStream()


class _FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeCompletions()


@pytest.mark.asyncio
async def test_openai_compatible_llm_omits_extra_body_without_thinking():
    llm = AsyncLLM(
        model="test-model",
        base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        thinking=None,
    )
    fake_client = _FakeClient()
    llm.client = fake_client

    result = [chunk async for chunk in llm.chat_completion([{"role": "user", "content": "hi"}])]

    assert result == []
    assert "extra_body" not in fake_client.chat.completions.kwargs


@pytest.mark.asyncio
async def test_openai_compatible_llm_sends_extra_body_with_thinking():
    llm = AsyncLLM(
        model="test-model",
        base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        thinking="disabled",
    )
    fake_client = _FakeClient()
    llm.client = fake_client

    result = [chunk async for chunk in llm.chat_completion([{"role": "user", "content": "hi"}])]

    assert result == []
    assert fake_client.chat.completions.kwargs["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
