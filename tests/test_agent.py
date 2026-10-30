from __future__ import annotations

import asyncio
import json

from conftest import tool_call

from cloudbrowser.agent import api_history, repair_messages


async def wait_for(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(.01)
    await asyncio.wait_for(wait(), 5)


async def test_browser_action_needs_explicit_approval_and_executes_once(make_agent):
    agent = make_agent(tool_call("browser_click", {"snapshot_id": "latest", "element_id": "e1"}))
    await agent.start()
    try:
        job = agent.enqueue("Klik tombol Go", "tg:101")
        assert agent.enqueue("Klik tombol Go", "tg:101")["id"] == job["id"]
        await wait_for(lambda: bool(agent.store.pending_approvals()))
        assert agent.browser.calls == []
        approval = agent.store.pending_approvals()[0]
        assert agent.decide(approval["id"], True)
        assert not agent.decide(approval["id"], True)
        await asyncio.wait_for(agent.queue.join(), 5)
        assert len(agent.browser.calls) == 1
        assert agent.store.job(job["id"])["status"] == "completed"
    finally:
        await agent.close()


async def test_rejection_pauses_without_clicking(make_agent):
    agent = make_agent(tool_call("browser_click", {"snapshot_id": "latest", "element_id": "e1"}))
    await agent.start()
    try:
        job = agent.enqueue("Review sebelum klik")
        await wait_for(lambda: bool(agent.store.pending_approvals()))
        agent.decide(agent.store.pending_approvals()[0]["id"], False)
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.browser.calls == []
        assert agent.store.job(job["id"])["status"] == "waiting_user"
    finally:
        await agent.close()


async def test_stop_cancels_approval_and_worker_can_accept_next_job(make_agent):
    agent = make_agent(tool_call("browser_fill", {"snapshot_id": "latest", "element_id": "e1", "text": "test"}))
    await agent.start()
    try:
        job = agent.enqueue("Isi field")
        await wait_for(lambda: bool(agent.waiters))
        approval_id = next(iter(agent.waiters))
        agent.stop()
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.store.job(job["id"])["status"] == "stopped"
        assert not agent.decide(approval_id, True)
        second = agent.enqueue("Tugas berikutnya")
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.store.job(second["id"])["status"] == "completed"
        assert not agent.browser.calls
    finally:
        await agent.close()


async def test_manual_login_pause_and_resume_uses_fresh_state(make_agent):
    agent = make_agent(tool_call("ask_user", {"question": "Login Google melalui dashboard."}))
    await agent.start()
    try:
        job = agent.enqueue("Buka Flow")
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.store.job(job["id"])["status"] == "waiting_user"
        observations = agent.browser.observations
        agent.resume(job["id"], "Login sudah selesai, lanjutkan.")
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.browser.observations > observations
        assert agent.store.job(job["id"])["status"] == "completed"
        assert "Login sudah selesai" in json.dumps(agent.ai.requests[-1])
    finally:
        await agent.close()


async def test_shutdown_during_pending_approval_does_not_hang(make_agent):
    agent = make_agent(tool_call("browser_click", {"snapshot_id": "latest", "element_id": "e1"}))
    await agent.start()
    job = agent.enqueue("Job yang belum disetujui")
    await wait_for(lambda: bool(agent.waiters))
    await asyncio.wait_for(agent.close(), 2)
    assert agent.store.job(job["id"])["status"] == "interrupted"
    assert not agent.store.pending_approvals()


async def test_unknown_tool_is_not_executed_and_configured_secrets_are_redacted(make_agent, settings):
    settings.ai_api_key = "test-only-secret-never-a-real-key"
    agent = make_agent(tool_call("execute_shell", {"command": "rm -rf /"}),
                       {"role": "assistant", "content": "debug: " + settings.ai_api_key})
    await agent.start()
    try:
        job = agent.enqueue("Tidak ada shell")
        await asyncio.wait_for(agent.queue.join(), 5)
        stored = agent.store.job(job["id"])
        assert settings.ai_api_key not in stored["messages"] + stored["result"]
        assert "[REDACTED]" in stored["result"]
        assert not agent.browser.calls
    finally:
        await agent.close()


async def test_auto_mode_and_invalid_arguments(make_agent):
    agent = make_agent(tool_call("browser_click", {"snapshot_id": "latest", "element_id": "e1", "unexpected": True}),
                       tool_call("browser_click", {"snapshot_id": "latest", "element_id": "e1"}, "call_2"))
    agent.store.set("approval_mode", "auto")
    await agent.start()
    try:
        agent.enqueue("Klik satu kali")
        await wait_for(lambda: bool(agent.store.pending_approvals()))
        assert agent.browser.calls == []
        agent.decide(agent.store.pending_approvals()[0]["id"], True)
        await asyncio.wait_for(agent.queue.join(), 5)
        assert len(agent.browser.calls) == 1
        assert not agent.store.pending_approvals()
    finally:
        await agent.close()


def test_recovery_never_replays_unfinished_browser_call(make_agent):
    agent = make_agent()
    job = agent.store.create_job("Tugas")
    messages = [{"role": "user", "content": "test"}, tool_call("browser_click", {"element_id": "e1"})]
    agent.store.update_job(job["id"], status="running", messages=messages)
    agent.store.approval(job["id"], "browser_click", "test")
    agent.store.recover()
    recovered = agent.store.job(job["id"])
    assert recovered["status"] == "interrupted"
    assert not agent.store.pending_approvals()
    repaired = repair_messages(json.loads(recovered["messages"]))
    assert repaired[-1]["role"] == "tool"
    assert "unknown" in repaired[-1]["content"]
    assert not agent.browser.calls


def test_history_trimming_preserves_tool_call_pairs():
    messages = [{"role": "user", "content": "original task"}]
    for i in range(15):
        messages += [tool_call("browser_observe", {}, f"call_{i}"),
                     {"role": "tool", "tool_call_id": f"call_{i}", "content": "x" * 1000}]
    trimmed = api_history(messages, max_chars=3000)
    assert len(json.dumps(trimmed)) < 4000
    assert trimmed[0]["content"] == "original task"
    ids = {call["id"] for msg in trimmed for call in msg.get("tool_calls", [])}
    assert all(msg["tool_call_id"] in ids for msg in trimmed if msg["role"] == "tool")
