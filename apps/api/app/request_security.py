"""Browser request checks for the single-user local workbench, not authentication."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class Origin:
    scheme: str
    hostname: str
    port: int


def parse_origin(value: str) -> Origin | None:
    if not value or any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            return None
        return Origin(parsed.scheme, parsed.hostname.lower(), port)
    except ValueError:
        return None


class LocalRequestMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: list[str], trusted_hosts: list[str]) -> None:
        self.app = app
        self.allowed_origins = {origin for value in allowed_origins if (origin := parse_origin(value)) is not None}
        self.trusted_hosts = {hostname.lower().strip("[]") for hostname in trusted_hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        hosts = headers.getlist("host")
        current = parse_origin(f"{scope['scheme']}://{hosts[0]}") if len(hosts) == 1 else None
        if current is None or current.hostname not in self.trusted_hosts:
            await JSONResponse({"detail": "Untrusted request host."}, status_code=400)(scope, receive, send)
            return
        origins = headers.getlist("origin")
        if origins:
            origin = parse_origin(origins[0]) if len(origins) == 1 else None
            if origin is None or (origin != current and origin not in self.allowed_origins):
                await JSONResponse({"detail": "Untrusted request origin."}, status_code=403)(scope, receive, send)
                return
        elif headers.get("sec-fetch-site") == "cross-site":
            # Image/no-cors GET requests can omit Origin, and some reads perform work.
            await JSONResponse({"detail": "Cross-site browser requests are not allowed."}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)
