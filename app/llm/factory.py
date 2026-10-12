"""根据配置装配具体的 LLM 客户端——这是唯一知道「有哪些实现」的地方。"""

from app.config import Settings
from app.core.errors import ConfigError
from app.core.retry import RetryPolicy
from app.llm.base import LLMClient
from app.llm.fake import FakeLLM
from app.llm.openai_compatible import OpenAICompatibleLLM


def build_llm(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.strip().lower()

    if provider == "fake":
        return FakeLLM(model=settings.llm_model)

    if provider == "api":
        return OpenAICompatibleLLM(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            connect_timeout=settings.llm_connect_timeout,
            read_timeout=settings.llm_timeout,
            max_tokens=settings.llm_max_tokens,
            policy=RetryPolicy(
                max_retries=settings.llm_max_retries,
                base_delay=settings.llm_retry_base_delay,
                max_delay=settings.llm_retry_max_delay,
                retry_after_cap=settings.llm_retry_after_cap,
            ),
        )

    raise ConfigError(f"未知的 LLM_PROVIDER：{settings.llm_provider}（应为 fake 或 api）")
