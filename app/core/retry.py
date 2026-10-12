"""重试与退避策略（与具体厂商无关的通用工具）。

单独成模块的原因：这些逻辑（哪些错误可重试、退避多久、如何解析 Retry-After）
都是纯函数，可以脱离网络单独测试——这正是"工程可测性"的体现。
"""

import json
import random
from dataclasses import dataclass
from typing import Any

# 只有这些状态码值得重试：
#   408 请求超时 / 409 冲突 / 425 太早 / 429 限流
#   500 502 503 504 服务端临时故障
# 4xx 里的 400/401/403/404/422 属于「请求本身有问题」，重试没有意义。
RETRYABLE_STATUS: frozenset[int] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class RetryableUpstreamError(Exception):
    """可重试的上游错误（网络故障 / 限流 / 5xx）。"""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


def is_retryable_status(status: int) -> bool:
    return status in RETRYABLE_STATUS


@dataclass
class RetryPolicy:
    """指数退避 + 抖动。

        delay(n) = min(base * 2^n, max_delay)      # 逐次翻倍、触顶封顶
        实际等待 = random(0, delay)                 # full jitter，打散重试时刻

    抖动的作用：若大量客户端在同一时刻失败，它们会「同步地」一起重试
    （惊群 / thundering herd），反而把上游再次打垮。随机化能摊平这股冲击。
    """

    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    # 上游 Retry-After 的采纳上限：避免它给个很大的值（实测遇到过 53s）把请求长时间挂住。
    # 代价是被压到上限后可能重试仍失败——若你的场景更在意「等到能成功」，就把它调大。
    retry_after_cap: float = 30.0
    jitter: bool = True

    def delay_for(self, attempt: int) -> float:
        """第 attempt 次重试（从 0 开始）应等待的秒数。"""
        capped = min(self.base_delay * (2 ** attempt), self.max_delay)
        if self.jitter:
            return random.uniform(0.0, capped)
        return capped

    def wait_before_retry(self, attempt: int, retry_after: float | None) -> float:
        """本次重试前等多久。

        优先采纳上游给的 Retry-After（上游比我们更清楚何时能恢复），但不超过
        ``retry_after_cap``；上游没给才走指数退避 + 抖动。
        """
        if retry_after is not None:
            return min(max(0.0, retry_after), self.retry_after_cap)
        return self.delay_for(attempt)


def _find_number(obj: Any, keys: frozenset[str]) -> float | None:
    """在嵌套的 JSON 结构里递归找某个数值字段。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
            found = _find_number(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_number(item, keys)
            if found is not None:
                return found
    return None


def parse_retry_after(headers: Any, body_text: str = "") -> float | None:
    """解析上游要求的重试等待时间（秒），解析不到返回 None。

    优先看标准 HTTP 头 ``Retry-After``（只处理秒数形式）；
    其次在响应 body 里找 ``retry_after_seconds`` / ``retry_after`` 字段——
    本项目实测的上游（南航 token 服务）就是把等待秒数放在 body 里的。
    """
    if headers:
        raw = headers.get("retry-after")
        if raw:
            try:
                return max(0.0, float(str(raw).strip()))
            except ValueError:
                pass  # 罕见：Retry-After 用 HTTP-date 形式，此处暂不处理

    if not body_text:
        return None
    try:
        obj = json.loads(body_text)
    except (json.JSONDecodeError, TypeError):
        return None
    return _find_number(obj, frozenset({"retry_after_seconds", "retry_after"}))
