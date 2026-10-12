from fastapi import APIRouter, Request

from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """健康检查：顺便暴露当前用的是哪个 provider / 模型，方便排障。"""
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        provider=settings.llm_provider,
        model=settings.llm_model,
        version=settings.app_version,
    )
