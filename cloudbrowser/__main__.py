from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys

from .config import configure, configure_a2a, configure_studio, data_directory, load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Cloudbrowser — Telegram-controlled browser and video agent")
    parser.add_argument("command", nargs="?", choices=["serve", "configure", "configure-a2a", "configure-studio", "doctor"], default="serve")
    parser.add_argument("--if-missing", action="store_true", help="Do not prompt if configuration already exists")
    parser.add_argument("--live", action="store_true", help="Doctor only: verify Telegram and make one small AI API call")
    parser.add_argument("--host", help="Override HTTP bind host")
    parser.add_argument("--port", type=int, help="Override HTTP port")
    args = parser.parse_args()
    directory = data_directory()
    try:
        if args.command == "configure":
            configure(directory, args.if_missing)
            return
        if args.command == "configure-a2a":
            configure_a2a(directory)
            return
        if args.command == "configure-studio":
            configure_studio(directory)
            return
        if not (directory / "config.json").exists():
            configure(directory)
        settings = load_settings(directory)
        if args.command == "doctor":
            info = {"configuration": "valid", "model": settings.ai_model,
                    "ai_key_present": bool(settings.ai_api_key), "vision": settings.ai_vision,
                    "telegram_owner_configured": settings.telegram_owner_id > 0,
                    "ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe")),
                    "display_present": bool(os.environ.get("DISPLAY")), "headless": settings.headless,
                    "live_api_verified": False}
            if args.live:
                from .llm import AIClient
                from .telegram import TelegramClient
                from .tools import TOOLS

                async def check():
                    ai = AIClient(settings)
                    telegram = TelegramClient(settings.telegram_bot_token)
                    try:
                        await ai.complete([{"role": "user", "content": "Reply OK. Do not call any tools."}],
                                          [tool.schema() for tool in TOOLS[:1]])
                        if settings.telegram_enabled:
                            await telegram.call("getMe")
                    finally:
                        await ai.close()
                        await telegram.close()
                asyncio.run(check())
                info["live_api_verified"] = True
            print(json.dumps(info, indent=2))
            return
        import uvicorn

        from .web import create_app
        host = args.host or os.environ.get("CLOUDBROWSER_BIND_HOST", settings.bind_host)
        port = args.port or settings.port
        print(f"Cloudbrowser: http://{host}:{port} — login menggunakan password dashboard.")
        print("Kirim /start ke bot Telegram setelah server siap. Tekan Ctrl+C untuk berhenti.")
        uvicorn.run(create_app(settings, directory), host=host, port=port, workers=1,
                    access_log=False, log_level="warning", proxy_headers=False)
    except (ValueError, OSError) as exc:
        print(f"Cloudbrowser: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
