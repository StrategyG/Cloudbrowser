from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from urllib.parse import urlsplit


class NetworkPolicy:
    """Browser guardrails; deploy with an egress firewall for network isolation."""

    def __init__(self, domains: list[str]):
        self.domains = domains
        self.cache: dict[str, float] = {}

    def allowed_host(self, hostname: str) -> bool:
        return any(hostname == d or hostname.endswith("." + d) for d in self.domains)

    async def check(self, url: str, *, navigation: bool = False, websocket: bool = False) -> None:
        parts = urlsplit(url)
        schemes = {"ws", "wss"} if websocket else {"http", "https"}
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme not in schemes or not host or parts.username or parts.password:
            raise ValueError("Browser URL must use HTTP(S) without credentials.")
        if parts.port not in {None, 80, 443}:
            raise ValueError("Browser access is limited to public web ports 80 and 443.")
        if "." not in host or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("Private hostnames are blocked.")
        if navigation and not self.allowed_host(host):
            raise ValueError("Domain belum diizinkan. Tambahkan domain melalui konfigurasi server.")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            if self.cache.get(host, 0) > time.monotonic():
                return
            try:
                resolved = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), 5
                )
                addresses = [ipaddress.ip_address(row[4][0]) for row in resolved]
            except (OSError, TimeoutError) as exc:
                raise ValueError("Browser DNS lookup failed.") from exc
        if not addresses or any(not address.is_global for address in addresses):
            raise ValueError("Browser access to local, private and metadata addresses is blocked.")
        self.cache[host] = time.monotonic() + 30
