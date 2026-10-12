"""LLM 客户端的统一契约。

有了这个抽象，上层路由不关心底层是 fake 还是真实 API，
换模型 / 换厂商时只改 factory，不动业务代码。
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

ChunkType = Literal["reasoning", "content"]


@dataclass(slots=True)
class Chunk:
    """一段流式增量。

    type="reasoning"：模型的思维链（推理模型才有，如 glm-5.3-flash）；
    type="content"  ：面向用户的正式回答。
    """

    type: ChunkType
    text: str


class LLMClient(Protocol):
    model: str

    def stream_chat(self, messages: list[dict]) -> AsyncIterator[Chunk]:
        """messages 形如 [{"role": "user", "content": "..."}]，逐段 yield 增量。"""
        ...
