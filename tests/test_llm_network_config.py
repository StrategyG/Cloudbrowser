from __future__ import annotations

import json
import os
import socket

import httpx
import pytest

from cloudbrowser.config import load_settings, password_matches, save_settings
from cloudbrowser.llm import AIClient
from cloudbrowser.network import NetworkPolicy
from cloudbrowser.process_lock import ProcessLock


async def test_compatible_ai_client_builds_expected_http_request(settings):
    captured = []
    settings.ai_api_key = "test-only-key"

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]})

    ai = AIClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        assert (await ai.complete([{"role": "user", "content": "hello"}], []))["content"] == "OK"
        assert str(captured[0].url) == "http://127.0.0.1:9999/v1/chat/completions"
        assert captured[0].headers["authorization"] == "Bearer test-only-key"
        assert json.loads(captured[0].content)["model"] == settings.ai_model
    finally:
        await ai.close()


async def test_ai_errors_do_not_expose_credentials_and_invalid_calls_fail_closed(settings):
    settings.ai_api_key = "test-only-api-secret"
    for status, payload in [(401, {"error": settings.ai_api_key}),
                            (200, {"choices": [{"message": {"role": "assistant", "tool_calls": [
                                {"function": {"name": "browser_click", "arguments": "{}"}}
                            ]}}]})]:
        ai = AIClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(lambda request, status=status, payload=payload: httpx.Response(status, json=payload))))
        try:
            with pytest.raises(ValueError) as error:
                await ai.complete([], [])
            assert settings.ai_api_key not in str(error.value)
        finally:
            await ai.close()


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1", "http://localhost", "file:///etc/passwd", "http://[::1]", "https://google.com:8000", "https://user:pass@google.com"])
async def test_browser_blocks_private_urls(url):
    with pytest.raises(ValueError):
        await NetworkPolicy(["google.com"]).check(url)


async def test_browser_blocks_dns_to_private_ip_and_deceptive_domain(monkeypatch):
    import asyncio
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ValueError):
        await NetworkPolicy(["google.com"]).check("https://google.com", navigation=True)
    with pytest.raises(ValueError):
        await NetworkPolicy(["google.com"]).check("https://google.com.evil.example", navigation=True)


def test_settings_saved_privately_and_password_not_stored(settings, tmp_path):
    settings.ai_api_key = "test-only-secret"
    save_settings(tmp_path, settings)
    loaded = load_settings(tmp_path)
    assert loaded.ai_model == settings.ai_model
    assert loaded.ai_api_key == settings.ai_api_key
    assert "test-dashboard-password" not in (tmp_path / "config.json").read_text()
    assert password_matches("test-dashboard-password", loaded.dashboard_password_hash)
    if os.name != "nt":
        assert (tmp_path / "config.json").stat().st_mode & 0o777 == 0o600
        assert tmp_path.stat().st_mode & 0o777 == 0o700


def test_second_server_cannot_own_same_directory(tmp_path):
    first, second = ProcessLock(tmp_path / "server.lock"), ProcessLock(tmp_path / "server.lock")
    first.acquire()
    try:
        with pytest.raises(ValueError):
            second.acquire()
    finally:
        first.release()
