"""统一异常体系 + 全局异常处理器。

原则：业务代码只抛 AppError 的子类，由全局处理器统一转成 JSON，
避免每个路由里写一堆 try/except。
"""

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务异常基类。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class LLMError(AppError):
    """调用上游模型失败。用 502 表示是「上游」的问题，不是我们自己的 bug。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502)


class ConfigError(AppError):
    """配置错误，例如 provider 名字写错、缺少 key。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=500)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"type": exc.__class__.__name__, "message": exc.message}},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # 生产环境这里应该写日志 / 上报，而不是把堆栈暴露给用户
    return JSONResponse(
        status_code=500,
        content={"error": {"type": "InternalError", "message": "服务器内部错误"}},
    )
