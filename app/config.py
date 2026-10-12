"""集中配置：所有可变参数都从 .env 读取，代码里不出现硬编码密钥。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "agent-day1-skeleton"
    app_version: str = "0.1.0"

    # fake = 本地假模型（无需 key，用于跑通链路/写测试）
    # api  = 调用 OpenAI 兼容接口（DeepSeek / GLM / Qwen / OpenAI ...）
    llm_provider: str = "fake"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 2048

    # 超时（秒）：connect=建连；timeout=读取（流式下指两个数据块之间的最大间隔）
    llm_connect_timeout: float = 5.0
    llm_timeout: float = 60.0

    # 重试：指数退避 + 抖动
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 0.5
    llm_retry_max_delay: float = 8.0
    # 上游 Retry-After 的采纳上限（避免请求被长时间挂住）
    llm_retry_after_cap: float = 30.0

    # 是否把推理模型的思维链(reasoning)一并下发给前端
    llm_show_reasoning: bool = True


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置读取，保证全局只有一份实例。"""
    return Settings()
