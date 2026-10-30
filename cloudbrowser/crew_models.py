from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .schemas import Input


class AgentDefinition(Input):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    name: str = Field(min_length=1, max_length=80)
    profile: Literal["writer", "browser", "editor", "reviewer"]
    instructions: str = Field(min_length=10, max_length=4000)


class ExpectedOutput(Input):
    kind: Literal["text", "video", "browser"]
    width: int | None = Field(default=None, ge=1, le=3840)
    height: int | None = Field(default=None, ge=1, le=3840)
    fps: float | None = Field(default=None, gt=0, le=120)
    duration_seconds: float | None = Field(default=None, gt=0, le=7200)
    duration_tolerance: float = Field(default=0.5, ge=0, le=5)
    url_contains: str = Field(default="", max_length=300)
    text_contains: str = Field(default="", max_length=300)
    url_origin: str = Field(default="", max_length=300)
    has_audio: bool | None = None
    min_size_bytes: int = Field(default=1, ge=1)
    max_size_bytes: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_requirements(self):
        if self.kind != "video" and any(value is not None for value in
                                        (self.width, self.height, self.fps, self.duration_seconds, self.has_audio)):
            raise ValueError("Video properties require kind=video.")
        if self.kind != "browser" and (self.url_origin or self.url_contains):
            raise ValueError("URL requirements require kind=browser.")
        if self.kind == "video" and self.text_contains:
            raise ValueError("Text matching is supported for text and browser output, not video.")
        if self.max_size_bytes is not None and self.max_size_bytes < self.min_size_bytes:
            raise ValueError("Maximum output size cannot be smaller than the minimum.")
        if self.url_origin:
            origin = urlsplit(self.url_origin)
            if (origin.scheme not in {"http", "https"} or not origin.hostname or origin.username
                    or origin.password or origin.path not in {"", "/"} or origin.query or origin.fragment):
                raise ValueError("url_origin must be an HTTP(S) origin without a path or credentials.")
        return self


class WorkflowStep(Input):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    description: str = Field(min_length=10, max_length=2000)
    depends_on: list[str] = Field(default_factory=list, max_length=8)
    expected: ExpectedOutput


class Workflow(Input):
    objective: str = Field(min_length=1, max_length=4000)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_graph(self):
        seen = set()
        for step in self.steps:
            if step.id in seen or not set(step.depends_on) <= seen:
                raise ValueError("Steps must have unique IDs and depend only on earlier steps; cycles are forbidden.")
            seen.add(step.id)
        return self


class Delegate(Input):
    agent_id: str
    step_id: str
    task: str = Field(min_length=1, max_length=8000)
    input_artifact_ids: list[str] = Field(default_factory=list, max_length=20)


class ReviewTask(Input):
    task_id: str
    reviewer_id: str


class ReviewVerdict(Input):
    passed: bool
    summary: str = Field(min_length=1, max_length=2000)
    issues: list[str] = Field(default_factory=list, max_length=20)


class TaskID(Input):
    task_id: str


class PeerTask(Input):
    peer_id: str
    task: str = Field(min_length=1, max_length=8000)


class PeerID(Input):
    peer_id: str
