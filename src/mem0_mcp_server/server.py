"""MCP server that exposes Mem0 REST endpoints as MCP tools."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, TypeVar

import structlog
from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mem0 import MemoryClient
from pydantic import Field

from .schemas import (
    AddMemoryArgs,
    ConfigSchema,
    DeleteAllArgs,
    DeleteEntitiesArgs,
    GetMemoriesArgs,
    SearchMemoriesArgs,
    ToolMessage,
)

load_dotenv()

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    log_format = os.getenv("LOG_FORMAT", "console")
    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer() if log_format != "json" else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()
logger = structlog.get_logger("mem0_mcp_server")


# ---------------------------------------------------------------------------
# Configuration dataclass (replaces global mutable state)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServerConfig:
    """Immutable server configuration. Replaces global mutable state."""

    api_key: str | None = None
    default_user_id: str | None = None
    enable_graph_default: bool = False
    disable_dns_rebinding: bool = False
    host: str = "127.0.0.1"
    port: int = 8081


# ---------------------------------------------------------------------------
# Thread-safe TTL cache for MemoryClient (replaces lru_cache)
# ---------------------------------------------------------------------------

_client_cache: dict[str, tuple[MemoryClient, float]] = {}
_cache_lock = Lock()
_CACHE_TTL = 3600.0


def _mem0_client(api_key: str) -> MemoryClient:
    """Create or retrieve a cached MemoryClient with TTL-based expiration."""
    if not api_key.startswith("m0-") or len(api_key) < 10:
        raise ValueError("Invalid MEM0_API_KEY format. Expected format: m0-...")

    now = time.monotonic()
    with _cache_lock:
        if api_key in _client_cache:
            client, created_at = _client_cache[api_key]
            if now - created_at < _CACHE_TTL:
                return client

        client = MemoryClient(api_key=api_key)
        _client_cache[api_key] = (client, now)

        # Evict expired entries
        expired = [k for k, (_, t) in _client_cache.items() if now - t >= _CACHE_TTL]
        for k in expired:
            del _client_cache[k]

        return client


def clear_client_cache() -> None:
    """Clear the client cache. Useful for testing."""
    with _cache_lock:
        _client_cache.clear()


# ---------------------------------------------------------------------------
# Smithery compatibility
# ---------------------------------------------------------------------------

try:
    from smithery.decorators import smithery
except ImportError:  # pragma: no cover

    class _SmitheryFallback:
        @staticmethod
        def server(*args: Any, **kwargs: Any):
            def decorator(func: Any) -> Any:
                return func

            return decorator

    smithery = _SmitheryFallback()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Environment defaults
# ---------------------------------------------------------------------------

ENV_API_KEY = os.getenv("MEM0_API_KEY")
ENV_DEFAULT_USER_ID = os.getenv("MEM0_DEFAULT_USER_ID", "mem0-mcp")
ENV_ENABLE_GRAPH_DEFAULT = os.getenv("MEM0_ENABLE_GRAPH_DEFAULT", "false").lower() in {
    "1",
    "true",
    "yes",
}
ENV_DISABLE_DNS_REBINDING_PROTECTION = os.getenv("MEM0_DISABLE_DNS_REBINDING_PROTECTION", "false").lower() in {
    "1",
    "true",
    "yes",
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _config_value(source: Any, field_name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def _with_default_filters(
    default_user_id: str,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure filters exist and include the default user_id at the top level."""
    if not filters:
        return {"AND": [{"user_id": default_user_id}]}
    if not any(key in filters for key in ("AND", "OR", "NOT")):
        filters = {"AND": [filters]}
    has_user = json.dumps(filters, sort_keys=True).find('"user_id"') != -1
    if not has_user:
        and_list = filters.setdefault("AND", [])
        if not isinstance(and_list, list):
            raise ValueError("filters['AND'] must be a list when present.")
        and_list.insert(0, {"user_id": default_user_id})
    return filters


def _mem0_call(func: Any, *args: Any, **kwargs: Any) -> str:
    """Call a Mem0 client method with retry logic. Always returns valid JSON string."""
    max_retries = 3
    base_delay = 1.0
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            result = func(*args, **kwargs)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            last_error = exc
            status = getattr(exc, "status", None)

            if status and 500 <= status < 600 and attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "mem0_call_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay=delay,
                    error=str(exc),
                )
                time.sleep(delay)
                continue

            logger.error("mem0_call_failed", error=str(exc), status=status)
            break

    return json.dumps(
        {
            "error": str(last_error),
            "status": getattr(last_error, "status", None),
            "payload": getattr(last_error, "payload", None),
        },
        ensure_ascii=False,
    )


def _resolve_settings(
    ctx: Context | None,
    config: ServerConfig | None = None,
) -> tuple[str, str, bool]:
    cfg = config or ServerConfig()
    session_config = getattr(ctx, "session_config", None)

    api_key = cfg.api_key or _config_value(session_config, "mem0_api_key") or ENV_API_KEY
    if not api_key:
        raise RuntimeError(
            "MEM0_API_KEY is required (via CLI args, Smithery config, session config, "
            "or environment) to run the Mem0 MCP server."
        )

    default_user = cfg.default_user_id or _config_value(session_config, "default_user_id") or ENV_DEFAULT_USER_ID

    enable_graph_default = _config_value(session_config, "enable_graph_default")
    if enable_graph_default is None:
        enable_graph_default = cfg.enable_graph_default or ENV_ENABLE_GRAPH_DEFAULT

    return api_key, default_user, enable_graph_default


def _default_enable_graph(enable_graph: bool | None, default: bool) -> bool:
    if enable_graph is None:
        return default
    return enable_graph


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


@smithery.server(config_schema=ConfigSchema)
def create_server(config: ServerConfig | None = None) -> FastMCP:
    """Create a FastMCP server usable via stdio, Docker, or Smithery."""
    cfg = config or ServerConfig()

    if not ENV_API_KEY and not cfg.api_key:
        logger.warning(
            "api_key_missing",
            detail="MEM0_API_KEY not set; tool invocations will fail until a key is supplied.",
        )

    host = os.getenv("HOST", cfg.host)
    port = int(os.getenv("PORT", str(cfg.port)))
    disable_dns = cfg.disable_dns_rebinding or ENV_DISABLE_DNS_REBINDING_PROTECTION

    server = FastMCP(
        "mem0",
        host=host,
        port=port,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=not disable_dns,
        ),
    )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @server.tool(
        description=(
            "Store a new preference, fact, or conversation snippet. "
            "Requires at least one: user_id, agent_id, or run_id."
        ),
    )
    def add_memory(
        text: Annotated[
            str,
            Field(description="Plain sentence summarizing what to store. Required even if `messages` is provided."),
        ],
        messages: Annotated[
            list[dict[str, str]] | None,
            Field(default=None, description="Structured conversation history with `role`/`content`."),
        ] = None,
        user_id: Annotated[
            str | None,
            Field(default=None, description="Override the default user scope for this write."),
        ] = None,
        agent_id: Annotated[str | None, Field(default=None, description="Optional agent identifier.")] = None,
        app_id: Annotated[str | None, Field(default=None, description="Optional app identifier.")] = None,
        run_id: Annotated[str | None, Field(default=None, description="Optional run identifier.")] = None,
        metadata: Annotated[
            dict[str, Any] | None,
            Field(default=None, description="Attach arbitrary metadata JSON to the memory."),
        ] = None,
        enable_graph: Annotated[
            bool | None,
            Field(default=None, description="Set true only if the caller explicitly wants Mem0 graph memory."),
        ] = None,
        ctx: Context | None = None,
    ) -> str:
        """Write durable information to Mem0."""
        api_key, default_user, graph_default = _resolve_settings(ctx, cfg)
        args = AddMemoryArgs(
            text=text,
            messages=[ToolMessage(**msg) for msg in messages] if messages else None,
            user_id=user_id if user_id else (default_user if not (agent_id or run_id) else None),
            agent_id=agent_id,
            app_id=app_id,
            run_id=run_id,
            metadata=metadata,
            enable_graph=_default_enable_graph(enable_graph, graph_default),
        )
        payload = args.model_dump(exclude_none=True)
        payload.setdefault("enable_graph", graph_default)
        conversation = payload.pop("messages", None)
        if not conversation:
            derived_text = payload.pop("text", None)
            if derived_text:
                conversation = [{"role": "user", "content": derived_text}]
            else:
                return json.dumps(
                    {"error": "messages_missing", "detail": "Provide either `text` or `messages`."},
                    ensure_ascii=False,
                )
        else:
            payload.pop("text", None)

        client = _mem0_client(api_key)
        return _mem0_call(client.add, conversation, **payload)

    @server.tool(
        description=(
            "Run a semantic search over existing memories.\n\n"
            "Use filters to narrow results. Common filter patterns:\n"
            '- Single user: {"AND": [{"user_id": "john"}]}\n'
            '- Agent memories: {"AND": [{"agent_id": "agent_name"}]}\n'
            '- Recent memories: {"AND": [{"user_id": "john"}, {"created_at": {"gte": "2024-01-01"}}]}\n'
            '- Multiple users: {"AND": [{"user_id": {"in": ["john", "jane"]}}]}\n'
            '- Cross-entity: {"OR": [{"user_id": "john"}, {"agent_id": "agent_name"}]}\n\n'
            "user_id is automatically added to filters if not provided."
        ),
    )
    def search_memories(
        query: Annotated[str, Field(description="Natural language description of what to find.")],
        filters: Annotated[
            dict[str, Any] | None,
            Field(default=None, description="Additional filter clauses (user_id injected automatically)."),
        ] = None,
        limit: Annotated[int | None, Field(default=None, description="Maximum number of results to return.")] = None,
        enable_graph: Annotated[
            bool | None,
            Field(default=None, description="Set true only when the user explicitly wants graph-derived memories."),
        ] = None,
        ctx: Context | None = None,
    ) -> str:
        """Semantic search against existing memories."""
        api_key, default_user, graph_default = _resolve_settings(ctx, cfg)
        args_obj = SearchMemoriesArgs(
            query=query, filters=filters, limit=limit, enable_graph=_default_enable_graph(enable_graph, graph_default)
        )
        payload = args_obj.model_dump(exclude_none=True)
        payload["filters"] = _with_default_filters(default_user, payload.get("filters"))
        payload.setdefault("enable_graph", graph_default)
        client = _mem0_client(api_key)
        return _mem0_call(client.search, **payload)

    @server.tool(
        description=(
            "Page through memories using filters instead of search.\n\n"
            "Use filters to list specific memories. Common filter patterns:\n"
            '- Single user: {"AND": [{"user_id": "john"}]}\n'
            '- Agent memories: {"AND": [{"agent_id": "agent_name"}]}\n\n'
            "Pagination: Use page (1-indexed) and page_size for browsing results.\n"
            "user_id is automatically added to filters if not provided."
        ),
    )
    def get_memories(
        filters: Annotated[
            dict[str, Any] | None,
            Field(default=None, description="Structured filters; user_id injected automatically."),
        ] = None,
        page: Annotated[int | None, Field(default=None, description="1-indexed page number when paginating.")] = None,
        page_size: Annotated[
            int | None, Field(default=None, description="Number of memories per page (default 10).")
        ] = None,
        enable_graph: Annotated[
            bool | None,
            Field(default=None, description="Set true only if the caller explicitly wants graph-derived memories."),
        ] = None,
        ctx: Context | None = None,
    ) -> str:
        """List memories via structured filters or pagination."""
        api_key, default_user, graph_default = _resolve_settings(ctx, cfg)
        args_obj = GetMemoriesArgs(
            filters=filters,
            page=page,
            page_size=page_size,
            enable_graph=_default_enable_graph(enable_graph, graph_default),
        )
        payload = args_obj.model_dump(exclude_none=True)
        payload["filters"] = _with_default_filters(default_user, payload.get("filters"))
        payload.setdefault("enable_graph", graph_default)
        client = _mem0_client(api_key)
        return _mem0_call(client.get_all, **payload)

    @server.tool(description="Delete every memory in the given user/agent/app/run but keep the entity.")
    def delete_all_memories(
        user_id: Annotated[
            str | None, Field(default=None, description="User scope to delete; defaults to server user.")
        ] = None,
        agent_id: Annotated[str | None, Field(default=None, description="Optional agent scope to delete.")] = None,
        app_id: Annotated[str | None, Field(default=None, description="Optional app scope to delete.")] = None,
        run_id: Annotated[str | None, Field(default=None, description="Optional run scope to delete.")] = None,
        ctx: Context | None = None,
    ) -> str:
        """Bulk-delete every memory in the confirmed scope."""
        api_key, default_user, _ = _resolve_settings(ctx, cfg)
        args_obj = DeleteAllArgs(user_id=user_id or default_user, agent_id=agent_id, app_id=app_id, run_id=run_id)
        payload = args_obj.model_dump(exclude_none=True)
        client = _mem0_client(api_key)
        return _mem0_call(client.delete_all, **payload)

    @server.tool(description="List which users/agents/apps/runs currently hold memories.")
    def list_entities(ctx: Context | None = None) -> str:
        """List users/agents/apps/runs with stored memories."""
        api_key, _, _ = _resolve_settings(ctx, cfg)
        client = _mem0_client(api_key)
        return _mem0_call(client.users)

    @server.tool(description="Fetch a single memory once you know its memory_id.")
    def get_memory(
        memory_id: Annotated[str, Field(description="Exact memory_id to fetch.")],
        ctx: Context | None = None,
    ) -> str:
        """Retrieve a single memory once the user has picked an exact ID."""
        api_key, _, _ = _resolve_settings(ctx, cfg)
        client = _mem0_client(api_key)
        return _mem0_call(client.get, memory_id)

    @server.tool(description="Overwrite an existing memory's text.")
    def update_memory(
        memory_id: Annotated[str, Field(description="Exact memory_id to overwrite.")],
        text: Annotated[str, Field(description="Replacement text for the memory.")],
        ctx: Context | None = None,
    ) -> str:
        """Overwrite an existing memory's text after the user confirms the exact memory_id."""
        api_key, _, _ = _resolve_settings(ctx, cfg)
        client = _mem0_client(api_key)
        return _mem0_call(client.update, memory_id=memory_id, text=text)

    @server.tool(description="Delete one memory after the user confirms its memory_id.")
    def delete_memory(
        memory_id: Annotated[str, Field(description="Exact memory_id to delete.")],
        ctx: Context | None = None,
    ) -> str:
        """Delete a memory once the user explicitly confirms the memory_id to remove."""
        api_key, _, _ = _resolve_settings(ctx, cfg)
        client = _mem0_client(api_key)
        return _mem0_call(client.delete, memory_id)

    @server.tool(description="Remove a user/agent/app/run record entirely (and cascade-delete its memories).")
    def delete_entities(
        user_id: Annotated[str | None, Field(default=None, description="Delete this user and its memories.")] = None,
        agent_id: Annotated[str | None, Field(default=None, description="Delete this agent and its memories.")] = None,
        app_id: Annotated[str | None, Field(default=None, description="Delete this app and its memories.")] = None,
        run_id: Annotated[str | None, Field(default=None, description="Delete this run and its memories.")] = None,
        ctx: Context | None = None,
    ) -> str:
        """Delete a user/agent/app/run (and its memories) once the user confirms the scope."""
        api_key, _, _ = _resolve_settings(ctx, cfg)
        args_obj = DeleteEntitiesArgs(user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id)
        if not any([args_obj.user_id, args_obj.agent_id, args_obj.app_id, args_obj.run_id]):
            return json.dumps(
                {"error": "scope_missing", "detail": "Provide user_id, agent_id, app_id, or run_id."},
                ensure_ascii=False,
            )
        payload = args_obj.model_dump(exclude_none=True)
        client = _mem0_client(api_key)
        return _mem0_call(client.delete_users, **payload)

    @server.prompt()
    def memory_assistant() -> str:
        """Get help with memory operations and best practices."""
        return (
            "You are using the Mem0 MCP server for long-term memory management.\n\n"
            "Quick Start:\n"
            "1. Store memories: Use add_memory to save facts, preferences, or conversations\n"
            "2. Search memories: Use search_memories for semantic queries\n"
            "3. List memories: Use get_memories for filtered browsing\n"
            "4. Update/Delete: Use update_memory and delete_memory for modifications\n\n"
            "Filter Examples:\n"
            '- User memories: {"AND": [{"user_id": "john"}]}\n'
            '- Agent memories: {"AND": [{"agent_id": "agent_name"}]}\n'
            '- Recent only: {"AND": [{"user_id": "john"}, {"created_at": {"gte": "2024-01-01"}}]}\n\n'
            "Tips:\n"
            "- user_id is automatically added to filters\n"
            '- Use "*" as wildcard for any non-null value\n'
            "- Combine filters with AND/OR/NOT for complex queries"
        )

    return server


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio."""
    parser = argparse.ArgumentParser(description="Mem0 MCP Server")
    parser.add_argument(
        "--api-key",
        help="DEPRECATED: Use --api-key-file or MEM0_API_KEY env var instead. "
        "API key passed via CLI args is visible in process listings.",
    )
    parser.add_argument(
        "--api-key-file",
        help="Path to file containing Mem0 API key (one line, no whitespace).",
    )
    parser.add_argument("--user-id", help="Default user ID (overrides MEM0_DEFAULT_USER_ID env var)")

    args = parser.parse_args()

    api_key: str | None = None
    if args.api_key_file:
        key_path = Path(args.api_key_file)
        if not key_path.exists():
            logger.error("api_key_file_not_found", path=str(key_path))
            sys.exit(1)
        api_key = key_path.read_text().strip()
    elif args.api_key:
        logger.warning(
            "api_key_cli_deprecated",
            detail="--api-key is deprecated and exposes the key in process listings. "
            "Use --api-key-file or MEM0_API_KEY env var instead.",
        )
        api_key = args.api_key

    config = ServerConfig(
        api_key=api_key,
        default_user_id=args.user_id,
    )

    server = create_server(config)
    effective_user = config.default_user_id or ENV_DEFAULT_USER_ID
    logger.info("server_starting", default_user=effective_user)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
