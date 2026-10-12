"""应用入口：装配配置、LLM 客户端、全局异常处理器、路由。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import get_settings
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.llm.factory import build_llm
from app.routers import chat, health

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化一次，整个应用生命周期复用（而不是每次请求都新建客户端）
    settings = get_settings()
    app.state.settings = settings
    app.state.llm = build_llm(settings)
    yield


app = FastAPI(
    title="Agent Day1 Skeleton",
    version="0.1.0",
    description="Agent 实习 Day1-2 工程地基骨架：配置管理 / 流式接口 / 异常处理 / 可测",
    lifespan=lifespan,
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(health.router)
app.include_router(chat.router)


@app.get("/", include_in_schema=False)
async def demo_page() -> FileResponse:
    """内置的流式聊天演示页（纯前端，自己解析并拼接 SSE）。"""
    return FileResponse(STATIC_DIR / "demo.html")
