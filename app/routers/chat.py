"""对话接口：流式 + 非流式两种形态。

要点（面试高频）：
- 流式（SSE）：逐段推送，用户能立刻看到输出，适合长回答 / 打字机效果；
- 非流式：一次性返回完整答案，实现简单、便于程序调用；
- 推理模型的输出分两条流：reasoning（思维链）与 content（正式回答），用 type 区分；
- 一旦流式响应开始，HTTP 状态码就定死了，所以「流中途出错」只能以事件形式下发。
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest, ChatResponse
from app.services.chat import collect_reply

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(data: dict) -> str:
    """把 dict 编码成一条 SSE 事件。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """非流式：一次性返回完整答案（内部复用流式再聚合）。"""
    llm = request.app.state.llm
    messages = [{"role": "user", "content": payload.message}]

    reasoning, reply = await collect_reply(llm, messages)

    if not request.app.state.settings.llm_show_reasoning:
        reasoning = ""

    return ChatResponse(reply=reply, reasoning=reasoning, model=llm.model)


@router.post("/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """流式：以 SSE 逐段推送 reasoning / content。"""
    llm = request.app.state.llm
    show_reasoning = request.app.state.settings.llm_show_reasoning
    messages = [{"role": "user", "content": payload.message}]

    async def event_generator():
        try:
            async for chunk in llm.stream_chat(messages):
                if await request.is_disconnected():
                    break  # 客户端主动断开，及时释放上游连接
                if chunk.type == "reasoning" and not show_reasoning:
                    continue
                yield _sse({"type": chunk.type, "delta": chunk.text, "done": False})
            yield _sse({"type": "done", "delta": "", "done": True})
        except Exception as e:  # noqa: BLE001 - 流中异常必须以事件形式下发
            yield _sse({"type": "error", "error": str(e), "done": True})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
