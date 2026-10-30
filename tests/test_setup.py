from __future__ import annotations

import json
from dataclasses import asdict

from cloudbrowser.config import configure, load_settings, pair_owner


def test_first_run_prompts_and_keeps_secrets_out_of_console(monkeypatch, tmp_path, capsys):
    responses = iter(["https://model.example/v1", "creator-tool-model", "n", "12345",
                      "google.com,labs.google,capcut.com", "y", "127.0.0.1"])
    secrets = iter(["test-only-ai-key", "12345:TEST_ONLY_TOKEN_1234567890123",
                    "my-dashboard-password", "my-dashboard-password"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(secrets))
    configure(tmp_path)
    settings = load_settings(tmp_path)
    assert settings.ai_model == "creator-tool-model"
    assert settings.telegram_owner_id == 12345
    assert settings.headless
    output = capsys.readouterr().out
    for secret in ("test-only-ai-key", "12345:TEST_ONLY_TOKEN_1234567890123", "my-dashboard-password"):
        assert secret not in output
    # Subsequent startup does not prompt again.
    configure(tmp_path, if_missing=True)


async def test_pairing_requires_matching_code_in_private_chat(monkeypatch):
    closed = []
    calls = []

    class FakeClient:
        def __init__(self, token):
            pass

        async def call(self, method, payload=None):
            calls.append(method)
            if method == "getMe":
                return {"username": "test_cloudbrowser_bot"}
            if method == "getWebhookInfo":
                return {}
            if len([name for name in calls if name == "getUpdates"]) == 1:
                return []
            return [
                {"update_id": 1, "message": {"text": "/pair TEST_CODE", "from": {"id": 999},
                                             "chat": {"id": -1, "type": "group"}}},
                {"update_id": 2, "message": {"text": "/pair TEST_CODE", "from": {"id": 12345},
                                             "chat": {"id": 12345, "type": "private"}}},
            ]

        async def close(self):
            closed.append(True)

    monkeypatch.setattr("cloudbrowser.telegram.TelegramClient", FakeClient)
    monkeypatch.setattr("secrets.token_hex", lambda length: "TEST_CODE")
    assert await pair_owner("not-a-real-token") == 12345
    assert closed == [True]


def test_old_config_keeps_model_settings_and_gains_a2a_defaults(settings, tmp_path):
    old = asdict(settings)
    for key in ["require_workflow", "max_agents", "agent_max_steps", "max_model_calls", "a2a_base_url", "a2a_api_key", "a2a_peers",
                "ai_max_output_tokens", "ai_context_chars", "max_job_output_tokens", "max_repeated_tool_errors",
                "auto_browser_actions", "role_models"]:
        old.pop(key)
    (tmp_path / "config.json").write_text(json.dumps(old))
    upgraded = load_settings(tmp_path)
    assert upgraded.ai_model == settings.ai_model
    assert upgraded.require_workflow is True
    assert upgraded.a2a_api_key == ""
