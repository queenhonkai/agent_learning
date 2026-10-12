# Day1 · FastAPI 工程骨架

Agent 实习 Day1-2「工程地基」的起点项目。目标不是功能多，而是**结构规范、开箱能跑、可测试、可扩展**——这正是把「会写研究脚本」升级成「会做工程」的第一课。

## 这个骨架演示了什么

| 工程能力 | 对应文件 |
|---|---|
| 分层目录结构（路由 / 业务 / 模型 / 配置分开） | `app/routers`、`app/services`、`app/llm`、`app/schemas.py`、`app/config.py` |
| `.env` 集中配置，密钥不硬编码 | `app/config.py`、`.env.example` |
| 流式接口（SSE），区分 reasoning / content 两条流 | `app/routers/chat.py` |
| 非流式接口（复用流式再聚合） | `app/services/chat.py` |
| 统一异常处理（含上游 429/5xx） | `app/core/errors.py` |
| 依赖可替换（fake ↔ 真实 API） | `app/llm/base.py`、`app/llm/factory.py` |
| 前端消费 SSE 的完整示例 | `static/demo.html` |
| 自动化测试（不依赖 API key） | `conftest.py`、`tests/` |

## 目录结构

```
day1-fastapi-skeleton/
├── app/
│   ├── main.py                  # 应用入口：装配配置/客户端/异常/路由/演示页
│   ├── config.py                # 从 .env 读取配置
│   ├── schemas.py               # 请求/响应模型（入参校验）
│   ├── core/
│   │   └── errors.py            # 异常体系 + 全局处理器
│   ├── services/
│   │   └── chat.py              # 业务逻辑：把流式增量聚合成完整结果
│   ├── llm/
│   │   ├── base.py              # LLM 客户端协议 + Chunk（增量类型）
│   │   ├── fake.py              # 本地假模型（无需 key）
│   │   ├── openai_compatible.py # 真实 API（OpenAI 兼容）
│   │   └── factory.py           # 按配置组装客户端
│   └── routers/
│       ├── health.py            # GET /health
│       └── chat.py              # POST /api/chat、POST /api/chat/stream
├── static/
│   └── demo.html                # 内置流式聊天演示页（纯前端）
├── tests/                       # pytest 测试
├── conftest.py                  # pytest 全局配置（强制 fake）
├── pyproject.toml               # pytest 配置
├── requirements.txt
├── .env.example                 # 配置模板（复制为 .env）
└── .gitignore
```

## 快速开始

```bash
conda activate agent
cd D:/agent项目/day1-fastapi-skeleton
pip install -r requirements.txt
copy .env.example .env          # Windows；Git Bash 用 cp
uvicorn app.main:app --reload --port 8000
```

- 聊天演示页（推荐先看这个）：<http://127.0.0.1:8000/>
- 接口文档：<http://127.0.0.1:8000/docs>

## 接口

### `GET /health` — 健康检查
```json
{"status": "ok", "provider": "api", "model": "glm-5.3-flash", "version": "0.1.0"}
```
给机器看的（负载均衡 / K8s 探针 / 监控），顺便暴露当前 provider 和模型，方便排障。

### `POST /api/chat` — 非流式（一次拿完整答案）
```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"你好\"}"
```
```json
{"reply": "你好！有什么可以帮你的吗？", "reasoning": "用户在打招呼…", "model": "glm-5.3-flash"}
```

### `POST /api/chat/stream` — 流式（SSE）
```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"你好\"}"
```
返回 SSE，`type` 区分两条流，最后以 `done` 事件收尾：
```
data: {"type": "reasoning", "delta": "用户", "done": false}   ← 思维链（推理模型）
data: {"type": "content",   "delta": "你好", "done": false}   ← 正式回答
data: {"type": "done",      "delta": "", "done": true}
```

> **为什么 Swagger 里看到的是一堆碎片？** 因为 `Try it out` 只是把原始响应体倒出来，它没有
> JS 去解析 SSE。想看"连起来"的效果，请打开演示页 `/`；流式接口设计上就是逐段推送的。

## 关于 reasoning 与流式的三个要点

1. **两条流**：推理模型（如 `glm-5.3-flash`）会先"想"再答，思维链用 `type=reasoning` 单独下发。
   `.env` 里 `LLM_SHOW_REASONING=false` 可关闭。非推理模型不会产生 reasoning 事件，前端需兼容。
2. **流式 vs 非流式**：流式 = 逐段推送、体验好；非流式 = 一次返回、实现简单易调用。
   本项目的非流式接口**内部复用流式再聚合**，体现"流式是基础能力"这一设计观点。
3. **流中错误**：一旦响应开始，HTTP 状态码就固定了，中途出错只能以 `type=error` 事件下发。

## 稳定性：超时 + 重试 + 退避

| 配置 | 默认 | 说明 |
|---|---|---|
| `LLM_CONNECT_TIMEOUT` | 5s | 建立 TCP 连接的超时 |
| `LLM_TIMEOUT` | 60s | **读取超时**；流式下指「两个数据块之间的最大间隔」，不是总时长 |
| `LLM_MAX_RETRIES` | 3 | 最大重试次数 |
| `LLM_RETRY_BASE_DELAY` | 0.5s | 指数退避基数（0.5 → 1 → 2 …） |
| `LLM_RETRY_MAX_DELAY` | 8s | 单次退避上限 |
| `LLM_RETRY_AFTER_CAP` | 30s | 上游 `Retry-After` 的采纳上限 |

四条规则（代码见 `app/core/retry.py`）：

1. **只有网络故障 / 429 / 5xx 才重试**；400/401/403/404 直接报错（请求本身有问题，重试无意义）。
2. **指数退避 + 抖动（full jitter）**：等待时间逐次翻倍并封顶，再叠加随机量，
   避免大量客户端同步重试造成"惊群"。
3. **优先遵守上游 `Retry-After`**（含 body 里的 `retry_after_seconds`），但受 `LLM_RETRY_AFTER_CAP` 限制，
   防止单个请求被长时间挂住。
4. **流式一旦已输出过内容就不再重试**——否则用户会看到重复的半句话。

> 实测：本项目对接的南航 token 服务会返回 `429 upstream_capacity_exhausted` 并给出
> `retry_after_seconds`（遇到过 1s 与 53s 两种），本机制能正确按其要求退避后重试成功。

## 切换到真实 API

编辑 `.env`：
```ini
LLM_PROVIDER=api
LLM_BASE_URL=https://token.nuaa.edu.cn/v1     # 注意填到 /v1 为止
LLM_API_KEY=sk-你的key
LLM_MODEL=glm-5.3-flash
```
重启服务即可，**代码一行都不用改**——这就是 `factory` 抽象的价值。

> 踩坑提醒：`base_url` 只填到 `/v1`。代码里是 `base_url + "/chat/completions"` 拼出来的，
> 若把完整路径填进去会变成 `/v1/chat/completions/chat/completions`。

## 跑测试

```bash
pytest
```
测试全程使用 fake provider，**不需要任何 API key**，任何机器上都能复现。

## 你该从这里学到什么（面试能讲）

1. **配置与代码分离**：密钥只进 `.env`，`.env` 永不提交 Git（见 `.gitignore`）。
2. **依赖倒置**：路由依赖 `LLMClient` 协议，不依赖具体实现，所以能换模型而不改业务。
3. **流式接口的坑**：响应一旦开始，状态码就固定了，中途出错只能靠事件下发。
4. **多流协议设计**：用 `type` 字段区分 reasoning / content，比塞两个字段更易扩展。
5. **分层**：路由只管 HTTP，业务逻辑放 `services`，上游协议封装在 `llm`。
6. **稳定性设计**：分层超时 + 可重试错误判定 + 指数退避 + 抖动 + Retry-After + 流式不回退，
   全部已实现（`app/core/retry.py`）。这是区分「会调 API」和「会做工程」的典型考点。
7. **可测性**：用 fake 实现让测试离线可跑，这是工程和「随手写的脚本」最本质的区别。
