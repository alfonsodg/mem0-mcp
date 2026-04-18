"""Shared Pydantic models for the Mem0 MCP server."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolMessage(BaseModel):
    role: str = Field(..., description="Role of the speaker, e.g., user or assistant.")
    content: str = Field(..., description="Full text of the utterance to store.")


class ConfigSchema(BaseModel):
    """Session-level overrides used when hosting via Smithery or HTTP."""

    mem0_api_key: str = Field(..., description="Mem0 API key (required)")
    default_user_id: str | None = Field(
        None,
        description="Default user_id injected into filters when unspecified.",
    )
    enable_graph_default: bool | None = Field(
        None,
        description="Default enable_graph toggle when clients omit the flag.",
    )


class AddMemoryArgs(BaseModel):
    text: str | None = Field(None, description="Simple sentence to remember.")
    messages: list[ToolMessage] | None = Field(None, description="Explicit role/content history.")
    user_id: str | None = Field(None, description="Override for the Mem0 user ID.")
    agent_id: str | None = Field(None, description="Optional agent identifier.")
    app_id: str | None = Field(None, description="Optional app identifier.")
    run_id: str | None = Field(None, description="Optional run identifier.")
    metadata: dict[str, Any] | None = Field(None, description="Opaque metadata to persist.")
    enable_graph: bool | None = Field(None, description="Opt into graph storage.")


class SearchMemoriesArgs(BaseModel):
    query: str = Field(..., description="Describe what you want to find.")
    filters: dict[str, Any] | None = Field(None, description="Additional filter clauses.")
    limit: int | None = Field(None, description="Optional maximum number of matches.")
    enable_graph: bool | None = Field(None, description="Set True for graph knowledge.")


class GetMemoriesArgs(BaseModel):
    filters: dict[str, Any] | None = Field(None, description="Structured filters.")
    page: int | None = Field(None, description="1-indexed page number.")
    page_size: int | None = Field(None, description="Number of memories per page.")
    enable_graph: bool | None = Field(None, description="Set True for graph knowledge.")


class DeleteAllArgs(BaseModel):
    user_id: str | None = Field(None, description="User scope to delete.")
    agent_id: str | None = Field(None, description="Optional agent scope filter.")
    app_id: str | None = Field(None, description="Optional app scope filter.")
    run_id: str | None = Field(None, description="Optional run scope filter.")


class DeleteEntitiesArgs(BaseModel):
    user_id: str | None = Field(None, description="Delete this user and all related memories.")
    agent_id: str | None = Field(None, description="Delete this agent and its memories.")
    app_id: str | None = Field(None, description="Delete this app and its memories.")
    run_id: str | None = Field(None, description="Delete this run and its memories.")
