"""对话相关的业务逻辑：把流式增量聚合成完整结果。"""

from app.llm.base import LLMClient


async def collect_reply(llm: LLMClient, messages: list[dict]) -> tuple[str, str]:
    """消费流式输出，聚合成 (reasoning, content)。

    这里刻意复用 ``stream_chat``，而不是另写一条非流式请求路径——因为它体现一个
    设计观点：**流式是基础能力，非流式只是在它之上做了一次聚合**。上游只维护一套
    解析逻辑，两个接口共享，减少重复和不一致。
    """
    reasoning_parts: list[str] = []
    content_parts: list[str] = []

    async for chunk in llm.stream_chat(messages):
        if chunk.type == "reasoning":
            reasoning_parts.append(chunk.text)
        else:
            content_parts.append(chunk.text)

    return "".join(reasoning_parts), "".join(content_parts)
