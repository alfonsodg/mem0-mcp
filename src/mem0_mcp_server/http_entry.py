"""Production HTTP entry point for Smithery and other container hosts."""

from __future__ import annotations

import os

from .server import create_server


def main() -> None:
    server = create_server()
    server.settings.host = os.getenv("HOST", server.settings.host)
    server.settings.port = int(os.getenv("PORT", str(server.settings.port)))

    @server.custom_route("/health", methods=["GET"])
    async def health_check(request):
        from starlette.responses import JSONResponse

        return JSONResponse({"status": "healthy", "service": "mem0-mcp-server"})

    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
