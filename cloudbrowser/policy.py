from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .tools import Tool


@dataclass(frozen=True)
class ActionDecision:
    approval_required: bool
    reason: str


def action_policy(settings: Settings, mode: str, tool: Tool) -> ActionDecision:
    """Only terminal-configured capabilities can relax a gate; model arguments cannot."""
    if not tool.approval:
        return ActionDecision(False, "Read, navigation or local preparation.")
    if mode == "auto" and tool.action in {"fill", "select"} and tool.action in settings.auto_browser_actions:
        return ActionDecision(False, "Owner preauthorized this form action in server configuration.")
    return ActionDecision(True, "Account actions and remote delegation require an exact owner decision.")
