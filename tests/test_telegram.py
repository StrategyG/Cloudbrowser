from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from cloudbrowser.telegram import TelegramClient, TelegramService, text_chunks


class FakeTelegram:
    def __init__(self):
        self.calls = []

    async def call(self, method, payload=None, **kwargs):
        self.calls.append((method, payload))
        return {"message_id": 1}


def update(text, *, user=12345, chat=None, chat_type="private", update_id=1):
    return {"update_id": update_id, "message": {"from": {"id": user}, "chat": {
        "id": user if chat is None else chat, "type": chat_type}, "text": text}}


def service(settings, make_agent):
    agent = make_agent()
    settings = replace(settings, telegram_enabled=True, telegram_owner_id=12345,
                       telegram_bot_token="12345:TEST_ONLY_NOT_A_REAL_BOT_TOKEN")
    client = FakeTelegram()
    return TelegramService(settings, agent.store, agent, agent.artifacts, client), agent, client


async def test_only_configured_owner_in_private_chat_can_create_jobs(settings, make_agent):
    bot, agent, client = service(settings, make_agent)
    await bot.handle(update("/run Open Flow", user=999))
    await bot.handle(update("/run Open Flow", chat=-10, chat_type="group"))
    await bot.handle(update("/run Open Flow", chat=999))
    assert not agent.store.jobs()
    assert not client.calls
    await bot.handle(update("/run Open Flow"))
    assert len(agent.store.jobs()) == 1
    await bot.handle(update("/run Open Flow"))
    assert len(agent.store.jobs()) == 1


async def test_unauthorized_callback_cannot_approve(settings, make_agent):
    bot, agent, client = service(settings, make_agent)
    called = []
    agent.decide = lambda *args: called.append(args) or True
    callback = {"callback_query": {"id": "q1", "from": {"id": 999}, "data": "approve:abcd",
                                   "message": {"chat": {"id": 12345, "type": "private"}}}}
    await bot.handle(callback)
    assert called == []
    callback["callback_query"]["from"]["id"] = 12345
    await bot.handle(callback)
    assert called == [("abcd", True)]


async def test_resumed_message_is_not_enqueued_again_on_telegram_retry(settings, make_agent):
    bot, agent, _client = service(settings, make_agent)
    job = agent.store.create_job("Login")
    agent.store.update_job(job["id"], status="waiting_user")
    await bot.handle(update("Login selesai", update_id=55))
    await bot.handle(update("Login selesai", update_id=55))
    assert len(agent.store.jobs()) == 1
    assert agent.queue.qsize() == 1


async def test_group_chat_cannot_change_mode(settings, make_agent):
    bot, agent, _client = service(settings, make_agent)
    await bot.handle(update("/mode auto", chat=-10, chat_type="supergroup"))
    assert agent.mode == "approve"
    await bot.handle(update("/mode auto"))
    assert agent.mode == "auto"


async def test_telegram_transport_errors_never_echo_token():
    token = "12345:TEST_ONLY_NOT_A_REAL_BOT_TOKEN"

    def fail(request):
        raise httpx.ConnectError(str(request.url), request=request)

    bot = TelegramClient(token, httpx.AsyncClient(transport=httpx.MockTransport(fail)))
    try:
        with pytest.raises(ValueError) as error:
            await bot.call("getMe")
        assert token not in str(error.value)
    finally:
        await bot.close()


def test_unicode_chunks_fit_telegram_utf16_limit():
    chunks = text_chunks("🦊" * 5000)
    assert "".join(chunks) == "🦊" * 5000
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 4096 for chunk in chunks)


async def test_owner_lifecycle_commands_and_health_without_secrets(settings, make_agent):
    bot, agent, client = service(settings, make_agent)
    bot.settings.ai_api_key = "synthetic-ci-secret-never-real"
    first = agent.store.create_job("Safe operation", "tg:queued")
    await bot.handle(update("/pause " + first["id"], user=999, update_id=100))
    assert agent.store.job(first["id"])["status"] == "queued"
    await bot.handle(update("/pause " + first["id"], update_id=101))
    assert agent.store.job(first["id"])["status"] == "paused"
    await bot.handle(update("/health", update_id=102))
    await bot.handle(update("/browser", update_id=103))
    await bot.handle(update("/tasks", update_id=104))
    await bot.handle(update("/report " + first["id"], update_id=105))
    await bot.handle(update("/cancel " + first["id"], update_id=106))
    assert agent.store.job(first["id"])["status"] == "cancelled"
    assert any(item["kind"] == "owner_interrupt_requested"
               and item["detail"] == "cancelled" for item in agent.store.events(first["id"]))
    outputs = "\\n".join(str(payload) for method, payload in client.calls if method == "sendMessage")
    assert "Database: OK" in outputs
    assert "NOT_STARTED" in outputs
    assert bot.settings.telegram_bot_token not in outputs
    assert bot.settings.ai_api_key not in outputs


async def test_newtask_command_is_idempotent(settings, make_agent):
    bot, agent, _client = service(settings, make_agent)
    await bot.handle(update("/newtask Build ARUSIA storyboard", update_id=150))
    await bot.handle(update("/newtask Build ARUSIA storyboard", update_id=150))
    rows = agent.store.jobs()
    assert len(rows) == 1
    assert rows[0]["goal"] == "Build ARUSIA storyboard"
