"""重试策略与客户端行为的测试。

用 httpx.MockTransport 把网络替换成可控的假响应，因此不需要真实 API、
也不需要任何等待——退避时间在测试里被压到 0.001s。
"""

import asyncio

import httpx
import pytest

from app.core.errors import LLMError
from app.core.retry import (
    RetryPolicy,
    RetryableUpstreamError,
    is_retryable_status,
    parse_retry_after,
)
from app.llm.base import Chunk
from app.llm.openai_compatible import OpenAICompatibleLLM


def _policy() -> RetryPolicy:
    return RetryPolicy(max_retries=3, base_delay=0.001, max_delay=0.002, jitter=False)


def _sse_body(text: str) -> bytes:
    return (
        f'data: {{"choices":[{{"delta":{{"content":"{text}"}}}}]}}\n'
        "\n"
        "data: [DONE]\n"
        "\n"
    ).encode()


async def _drain(llm: OpenAICompatibleLLM) -> list[Chunk]:
    return [c async for c in llm.stream_chat([{"role": "user", "content": "hi"}])]


def _client(handler, policy: RetryPolicy | None = None) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        policy=policy or _policy(),
        transport=httpx.MockTransport(handler),
    )


# --------------------------------------------------------------------------
# 纯逻辑：错误分类 / 退避计算 / Retry-After 解析
# --------------------------------------------------------------------------

def test_retryable_status_classification():
    for code in (408, 429, 500, 502, 503, 504):
        assert is_retryable_status(code), f"{code} 应该是可重试的"
    for code in (400, 401, 403, 404, 422):
        assert not is_retryable_status(code), f"{code} 不应该重试"


def test_backoff_grows_then_caps():
    p = RetryPolicy(max_retries=5, base_delay=0.5, max_delay=2.0, jitter=False)
    assert p.delay_for(0) == 0.5
    assert p.delay_for(1) == 1.0
    assert p.delay_for(2) == 2.0
    assert p.delay_for(3) == 2.0  # 触顶后不再增长


def test_jitter_stays_within_cap():
    p = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=4.0, jitter=True)
    for _ in range(100):
        assert 0.0 <= p.delay_for(5) <= 4.0


def test_wait_before_retry_prefers_and_caps_retry_after():
    p = RetryPolicy(
        max_retries=3, base_delay=0.5, max_delay=8.0, retry_after_cap=30.0, jitter=False
    )
    assert p.wait_before_retry(0, 5.0) == 5.0, "未超上限时应采纳上游的 Retry-After"
    assert p.wait_before_retry(0, 53.0) == 30.0, "超过上限时压到上限"
    assert p.wait_before_retry(1, None) == 1.0, "上游没给时走指数退避"


def test_parse_retry_after_from_header():
    assert parse_retry_after({"retry-after": "12"}, "") == 12.0


def test_parse_retry_after_from_body_field():
    body = '{"error":{"message":"cooling down","retry_after_seconds":23}}'
    assert parse_retry_after({}, body) == 23.0


def test_parse_retry_after_absent():
    assert parse_retry_after({}, '{"error":{"message":"nope"}}') is None
    assert parse_retry_after({}, "not-json") is None
    assert parse_retry_after({}, "") is None


# --------------------------------------------------------------------------
# 客户端行为：是否重试 / 重试几次 / 何时不重试
# --------------------------------------------------------------------------

def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                json={"error": {"message": "cooling down", "retry_after_seconds": 0}},
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            200, content=_sse_body("hello"), headers={"content-type": "text/event-stream"}
        )

    chunks = asyncio.run(_drain(_client(handler)))

    assert calls["n"] == 2, "429 应触发一次重试并成功"
    assert "".join(c.text for c in chunks) == "hello"


def test_does_not_retry_on_400():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            400, json={"error": {"message": "bad request"}},
            headers={"content-type": "application/json"},
        )

    with pytest.raises(LLMError):
        asyncio.run(_drain(_client(handler)))

    assert calls["n"] == 1, "400 是请求本身的问题，不该重试"


def test_gives_up_after_max_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            503, json={"error": {"message": "unavailable"}},
            headers={"content-type": "application/json"},
        )

    with pytest.raises(LLMError):
        asyncio.run(_drain(_client(handler)))

    assert calls["n"] == 1 + 3, "首次请求 + 3 次重试"


def test_no_retry_after_stream_already_emitted():
    """一旦已经输出过内容，就不能重试（否则用户会看到重复的半句话）。"""

    class FlakyOnce(OpenAICompatibleLLM):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.calls = 0

        async def _stream_once(self, messages):
            self.calls += 1
            yield Chunk("content", "partial")
            raise RetryableUpstreamError("连接中断", retry_after=None)

    llm = FlakyOnce(
        base_url="https://example.test/v1",
        api_key="k",
        model="m",
        policy=_policy(),
    )

    with pytest.raises(LLMError):
        asyncio.run(_drain(llm))

    assert llm.calls == 1, "已经输出过内容后不应再重试"


def test_client_rejects_missing_api_key():
    with pytest.raises(LLMError):
        OpenAICompatibleLLM(base_url="https://example.test/v1", api_key="", model="m")
