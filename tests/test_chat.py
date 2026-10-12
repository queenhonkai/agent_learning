import json

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def _collect_stream(resp) -> tuple[str, str, bool]:
    """分别拼接 reasoning 与 content 两条流，并返回是否正常收尾。"""
    reasoning: list[str] = []
    content: list[str] = []
    done = False
    for ln in resp.iter_lines():
        if not ln or not ln.startswith("data:"):
            continue
        obj = json.loads(ln[len("data:"):].strip())
        if obj.get("done"):
            done = True
            break
        if obj.get("type") == "reasoning":
            reasoning.append(obj.get("delta", ""))
        elif obj.get("type") == "content":
            content.append(obj.get("delta", ""))
    return "".join(reasoning), "".join(content), done


def test_chat_stream_splits_reasoning_and_content():
    with TestClient(app) as client:
        with client.stream("POST", "/api/chat/stream", json={"message": "你好"}) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            reasoning, content, done = _collect_stream(resp)

    assert done, "流必须以 done=True 正常收尾"
    assert reasoning, "推理模型应产出 reasoning 增量"
    assert "fake" in content, "content 应包含假模型标识"
    assert "你好" in content, "content 应回显用户输入"
    assert "fake" not in reasoning, "reasoning 与 content 应是两条独立的流"


def test_chat_sync_returns_full_reply():
    """非流式接口：一次拿到拼好的完整答案。"""
    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"message": "你好"})

    assert resp.status_code == 200
    body = resp.json()
    assert "fake" in body["reply"], "reply 应是拼接后的完整回答"
    assert "你好" in body["reply"]
    assert body["reasoning"], "应带上思维链"
    assert body["model"]


def test_reasoning_can_be_disabled(monkeypatch):
    monkeypatch.setenv("LLM_SHOW_REASONING", "false")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            with client.stream("POST", "/api/chat/stream", json={"message": "hi"}) as resp:
                reasoning, content, done = _collect_stream(resp)
            sync_body = client.post("/api/chat", json={"message": "hi"}).json()

        assert done
        assert content, "关掉 reasoning 后 content 仍应正常返回"
        assert reasoning == "", "关掉后流式不应收到任何 reasoning"
        assert sync_body["reasoning"] == "", "关掉后非流式也不应返回思维链"
    finally:
        get_settings.cache_clear()


def test_chat_empty_message_rejected():
    with TestClient(app) as client:
        resp = client.post("/api/chat/stream", json={"message": ""})

    # 入参校验失败 -> 422，说明 Field(min_length=1) 生效
    assert resp.status_code == 422
