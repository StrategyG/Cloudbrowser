"""Owner-configured Studio service; fixed routes, bounded transfers, no automatic retries."""
from __future__ import annotations

import json
import re
from typing import Literal

import httpx
from pydantic import Field

from .schemas import Input

PROJECT_ID = r"^[a-f0-9]{32}$"
ASSETS = {"png": ".png", "mesh": ".glb", "rig": ".glb", "manifest": ".json", "mp4": ".mp4",
          **{f"rig_{pose}": ".png" for pose in ("rest", "arms", "legs", "combo")}}


class StudioProject(Input):
    project_id: str = Field(pattern=PROJECT_ID)


class StudioCreate(Input):
    artifact_id: str = Field(pattern=PROJECT_ID)


class StudioStage(StudioProject):
    stage: str = Field(pattern=r"^(mesh|rig|render)$")


class StudioApproval(StudioProject):
    stage: str = Field(pattern=r"^(mesh|rig|manifest)$")


class StudioPlan(StudioProject):
    prompt: str = Field(min_length=1, max_length=1200)
    fps: Literal[24, 30, 60] = 24
    width: int = 1280
    height: int = 720
    character: str = Field(default="KIO", pattern=r"^[A-Za-z0-9_-]{1,70}$")


class StudioAsset(StudioProject):
    kind: str = Field(pattern=r"^(png|mesh|rig|manifest|mp4|rig_rest|rig_arms|rig_legs|rig_combo)$")


class StudioClient:
    def __init__(self, settings, artifacts, *, transport=None):
        self.settings, self.artifacts, self.transport = settings, artifacts, transport

    @property
    def enabled(self):
        return bool(self.settings.studio_base_url and self.settings.studio_api_token)

    async def request(self, method, path, *, body=None, files=None, binary=False):
        if not self.enabled:
            raise ValueError("Studio belum dikonfigurasi. Jalankan configure-studio di terminal server.")
        limit = self.artifacts.max_bytes if binary else 262144
        async with httpx.AsyncClient(base_url=self.settings.studio_base_url, transport=self.transport,
                                     timeout=120, follow_redirects=False,
                                     headers={"x-studio-token": self.settings.studio_api_token}) as client:
            async with client.stream(method, path, json=body, files=files) as response:
                if response.status_code >= 300:
                    raise ValueError(f"Studio returned HTTP {response.status_code}; inspect its project state before retrying.")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ValueError("Studio response exceeds the configured transfer limit.")
        if binary:
            return bytes(data)
        return json.loads(self.settings.redact(data.decode("utf-8")))

    @staticmethod
    def route(project_id):
        if not re.fullmatch(PROJECT_ID, project_id):
            raise ValueError("Invalid Studio project ID.")
        return "/api/projects/" + project_id

    async def execute(self, name, args):
        if name == "studio_create_project":
            path = self.artifacts.path(args["artifact_id"])
            suffix = path.suffix.casefold()
            max_bytes = {".png": 12 * 1024 * 1024, ".glb": 50 * 1024 * 1024}
            if suffix not in max_bytes or not 0 < path.stat().st_size <= max_bytes[suffix]:
                raise ValueError("Studio requires PNG up to 12 MiB or GLB up to 50 MiB.")
            media_type = "image/png" if suffix == ".png" else "model/gltf-binary"
            return await self.request("POST", "/api/projects", files={
                "asset": ("asset" + suffix, path.read_bytes(), media_type)
            })
        route = self.route(args["project_id"])
        if name == "studio_get_project":
            return await self.request("GET", route)
        if name == "studio_inspect_scene":
            return await self.request("GET", route + "/scene")
        if name == "studio_motion_preflight":
            return await self.request("GET", route + "/motion-qa")
        if name == "studio_preview_scene":
            if args["fps"] not in {24, 30, 60} or (args["width"], args["height"]) not in {(640, 360), (1280, 720), (1920, 1080)}:
                raise ValueError("Unsupported Studio FPS or resolution.")
            return await self.request("POST", route + "/plan-preview",
                                      body={k: v for k, v in args.items() if k != "project_id"})
        if name == "studio_start_stage":
            return await self.request("POST", route + "/" + args["stage"])
        if name == "studio_approve_stage":
            # Called only after the parent server's exact owner approval.
            return await self.request("POST", route + "/approve", body={"stage": args["stage"], "confirm": True})
        if name == "studio_plan_scene":
            if args["fps"] not in {24, 30, 60} or (args["width"], args["height"]) not in {(640, 360), (1280, 720), (1920, 1080)}:
                raise ValueError("Unsupported Studio FPS or resolution.")
            return await self.request("POST", route + "/prompt", body={k: v for k, v in args.items() if k != "project_id"})
        if name == "studio_import_asset":
            kind = args["kind"]
            if kind not in ASSETS:
                raise ValueError("Unsupported Studio artifact.")
            state = await self.request("GET", route)
            if kind == "mp4" and state.get("state") != "completed":
                raise ValueError("Studio render has not completed.")
            data = await self.request("GET", route + "/assets/" + kind, binary=True)
            if not data:
                raise ValueError("Studio returned an empty artifact.")
            artifact_id, path, filename = self.artifacts.allocate(f"studio_{args['project_id']}_{kind}" + ASSETS[kind])
            try:
                path.write_bytes(data)
                return {"artifact": self.artifacts.register(artifact_id, path, filename)}
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        raise ValueError("Unknown Studio tool.")
