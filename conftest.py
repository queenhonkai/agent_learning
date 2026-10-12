"""pytest 全局配置。

放在项目根目录有两个作用：
1) 让 pytest 把项目根加入 sys.path，测试里才能 import app；
2) 强制用 fake provider，保证测试不依赖任何 API key、可离线复现。
"""

import os

os.environ["LLM_PROVIDER"] = "fake"

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()
