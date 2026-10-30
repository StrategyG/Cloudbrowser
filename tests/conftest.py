from __future__ import annotations

import json

import pytest

from cloudbrowser.agent import Agent
from cloudbrowser.artifacts import Artifacts
from cloudbrowser.config import Settings, password_hash
from cloudbrowser.media import Media
from cloudbrowser.store import Store


@pytest.fixture(scope="session")
def dashboard_hash():
    return password_hash("test-dashboard-password")


@pytest.fixture
def settings(dashboard_hash):
    return Settings(ai_base_url="http://127.0.0.1:9999/v1", ai_model="test-tool-model",
                    telegram_enabled=False, dashboard_password_hash=dashboard_hash,
                    headless=True, chromium_sandbox=False, require_workflow=False)


class StubBrowser:
    context = None
    last_error = ""

    def __init__(self):
        self.calls = []
        self.observations = 0

    async def snapshot(self):
        self.observations += 1
        return {"snapshot_id": "latest", "url": "about:blank", "elements": [{"id": "e1", "label": "Go"}]}

    async def action(self, kind, args, **kwargs):
        self.calls.append((kind, args))
        return await self.snapshot()

    async def close(self):
        pass


def tool_call(name, args, call_id="call_1"):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    ]}


class FakeAI:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    async def complete(self, messages, tools):
        self.requests.append(messages)
        return self.responses.pop(0) if self.responses else {"role": "assistant", "content": "Selesai."}

    async def close(self):
        pass


@pytest.fixture
def make_agent(tmp_path, settings):
    stores = []

    def make(*responses, browser=None):
        store = Store(tmp_path)
        stores.append(store)
        artifacts = Artifacts(tmp_path, store)
        return Agent(settings, store, browser or StubBrowser(), artifacts, FakeAI(*responses), Media(artifacts))

    yield make
    for store in stores:
        store.close()
