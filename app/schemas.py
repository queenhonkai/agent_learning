"""请求 / 响应模型：用 Pydantic 做入参校验，非法输入直接被拦在门口。"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000, description="用户输入")
    session_id: str | None = Field(default=None, description="会话 ID，预留给多轮对话")


class ChatResponse(BaseModel):
    """非流式对话的响应：一次拿到完整结果。"""

    reply: str = Field(..., description="完整回答")
    reasoning: str = Field(default="", description="思维链（非推理模型为空）")
    model: str = Field(..., description="实际使用的模型")


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: str
    version: str
