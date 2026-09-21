"""n8n operator API: token reads, container hooks, chat proxy."""

from __future__ import annotations

from app.config import get_settings


def test_snapshot_accepts_api_token(client):
    res = client.get("/api/v1/snapshot", headers={"X-API-Key": "test-token"})
    assert res.status_code in (200, 503)


def test_hooks_container_requires_token(client):
    res = client.post("/api/v1/hooks/container", json={"container": "plex", "action": "restart"})
    assert res.status_code == 401


def test_hooks_container_denylist(client):
    res = client.post(
        "/api/v1/hooks/container",
        json={"container": "prometheus", "action": "stop"},
        headers={"X-API-Key": "test-token"},
    )
    assert res.status_code == 400
    assert "denylist" in res.json()["detail"]


def test_hooks_container_unknown_action(client):
    res = client.post(
        "/api/v1/hooks/container",
        json={"container": "plex", "action": "explode"},
        headers={"X-API-Key": "test-token"},
    )
    assert res.status_code == 422


def test_chat_proxy_requires_url(client):
    res = client.post("/api/v1/chat/n8n", json={"action": "sendMessage", "chatInput": "hi"})
    assert res.status_code == 400
    assert "not configured" in res.json()["detail"]


def test_chat_test_requires_url(client):
    res = client.post("/api/v1/chat/test")
    assert res.status_code == 400


def test_chat_proxy_forwards(client, monkeypatch):
    from app.main import app

    async def fake_merged():
        return get_settings().model_copy(
            update={"n8n_chat_webhook_url": "http://n8n.test/webhook/chat"}
        )

    class Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b'{"output":"hello-from-n8n"}'

    async def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert "n8n.test" in url
        body = kwargs.get("json") or kwargs.get("content")
        assert body is not None
        return Resp()

    monkeypatch.setattr("app.services.n8n_chat.settings_store.merged", fake_merged)
    monkeypatch.setattr(app.state.n8n_chat._client, "request", fake_request)

    res = client.post(
        "/api/v1/chat/n8n",
        json={"action": "sendMessage", "sessionId": "abc", "chatInput": "hi"},
    )
    assert res.status_code == 200
    assert res.json()["output"] == "hello-from-n8n"


def test_chat_page_renders(client):
    res = client.get("/chat")
    assert res.status_code == 200
    assert "Chat" in res.text
    assert "n8n-chat-cta" in res.text
