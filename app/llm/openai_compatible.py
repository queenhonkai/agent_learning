"""OpenAI 兼容协议的流式客户端（DeepSeek / GLM / Qwen / OpenAI / Moonshot 都能用）。

包含三件稳定性设计：
1. **分层超时**：connect（建连）与 read（两个数据块之间的最大间隔）分开设置。
   注意流式请求的 read 超时不是「整个请求总时长」——推理模型可能思考很久才吐第一个字。
2. **可重试判定**：只有网络故障 / 429 / 5xx 才重试；400/401/403/404 直接报错。
3. **指数退避 + 抖动**，并优先遵守上游给的 Retry-After。

⚠️ 流式的特殊约束：**一旦已经向下游输出过内容，就绝不能再重试**——否则用户会看到
重复的半句话。因此重试只发生在「还没有产出任何 chunk」的阶段。
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.core.errors import LLMError
from app.core.retry import (
    RetryPolicy,
    RetryableUpstreamError,
    is_retryable_status,
    parse_retry_after,
)
from app.llm.base import Chunk

logger = logging.getLogger(__name__)


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 60.0,
        write_timeout: float = 10.0,
        max_tokens: int = 2048,
        policy: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMError("缺少 API key：请在 .env 里设置 LLM_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.policy = policy or RetryPolicy()
        # transport 仅用于测试注入（httpx.MockTransport），生产保持 None
        self.transport = transport
        self.timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=write_timeout,
            pool=connect_timeout,
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, transport=self.transport)

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[Chunk]:
        last_error: RetryableUpstreamError | None = None

        for attempt in range(self.policy.max_retries + 1):
            emitted = False
            try:
                async for chunk in self._stream_once(messages):
                    emitted = True
                    yield chunk
                return
            except RetryableUpstreamError as e:
                last_error = e
                if emitted:
                    # 已经输出过内容，重试会造成重复 -> 直接失败
                    raise LLMError(f"流已开始输出后中断，无法重试：{e.message}") from e
                if attempt >= self.policy.max_retries:
                    break
                delay = self.policy.wait_before_retry(attempt, e.retry_after)
                logger.warning(
                    "上游失败（第 %d/%d 次尝试）：%.2fs 后重试 | %s",
                    attempt + 1,
                    self.policy.max_retries + 1,
                    delay,
                    e.message,
                )
                await asyncio.sleep(delay)

        assert last_error is not None  # 能走到这里说明至少失败过一次
        raise LLMError(
            f"重试 {self.policy.max_retries} 次后仍失败：{last_error.message}"
        ) from last_error

    async def _stream_once(self, messages: list[dict]) -> AsyncIterator[Chunk]:
        """单次请求：失败时区分「可重试」与「不可重试」，分别抛出不同异常。"""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": self.max_tokens,
        }

        try:
            async with self._client() as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread())[:400].decode("utf-8", "ignore")
                        if is_retryable_status(resp.status_code):
                            raise RetryableUpstreamError(
                                f"上游返回 {resp.status_code}: {body[:100]}",
                                retry_after=parse_retry_after(resp.headers, body),
                            )
                        raise LLMError(f"上游返回 {resp.status_code}: {body[:200]}")

                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            # 上游偶发的半截数据，跳过而不是让整个请求崩掉
                            continue
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}

                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            yield Chunk("reasoning", reasoning)

                        piece = delta.get("content")
                        if piece:
                            yield Chunk("content", piece)
        except httpx.HTTPError as e:
            # 连接失败 / 超时 / 流中断，都算可重试
            raise RetryableUpstreamError(f"网络错误：{e}") from e
