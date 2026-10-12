"""本地假模型：不依赖任何 API key。

它的价值不只是「占位」——它让整条流式链路和自动化测试可以在
任何机器上、任何时间、离线复现，这是工程可测性的关键。
同时它也会先发一段 reasoning 再发 content，用来验证「两条流」都通。
"""

import asyncio
from collections.abc import AsyncIterator

from app.llm.base import Chunk


class FakeLLM:
    def __init__(self, model: str = "fake-model", delay: float = 0.01) -> None:
        self.model = model
        self.delay = delay

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[Chunk]:
        user_text = messages[-1]["content"] if messages else ""

        # 模拟推理模型的思维链
        for ch in "（假模型无需思考，直接回答）":
            await asyncio.sleep(self.delay)
            yield Chunk("reasoning", ch)

        # 正式回答
        reply = f"[fake] 已收到：{user_text}。这是逐段返回的模拟回复。"
        for ch in reply:
            await asyncio.sleep(self.delay)
            yield Chunk("content", ch)
