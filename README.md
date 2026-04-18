# Mem0 MCP Server (Fork)

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

> Actively maintained fork of [mem0ai/mem0-mcp](https://github.com/mem0ai/mem0-mcp) (archived upstream).

`mem0-mcp-server-alfonsodg` wraps the official [Mem0](https://mem0.ai) Memory API as a Model Context Protocol (MCP) server so any MCP-compatible client (Claude Desktop, Cursor, Kiro, custom agents) can add, search, update, and delete long-term memories.

## Tools

| Tool                  | Description                                                                       |
| --------------------- | --------------------------------------------------------------------------------- |
| `add_memory`          | Save text or conversation history for a user/agent.                               |
| `search_memories`     | Semantic search across existing memories (filters + limit supported).             |
| `get_memories`        | List memories with structured filters and pagination.                             |
| `get_memory`          | Retrieve one memory by its `memory_id`.                                           |
| `update_memory`       | Overwrite a memory's text once the user confirms the `memory_id`.                 |
| `delete_memory`       | Delete a single memory by `memory_id`.                                            |
| `delete_all_memories` | Bulk delete all memories in the confirmed scope (user/agent/app/run).             |
| `delete_entities`     | Delete a user/agent/app/run entity (and its memories).                            |
| `list_entities`       | Enumerate users/agents/apps/runs stored in Mem0.                                  |

## Quick Start

### Installation

```bash
uv pip install mem0-mcp-server-alfonsodg
```

### Client Configuration

**Option 1: Using environment variables (recommended)**

```json
{
  "mcpServers": {
    "mem0": {
      "command": "uvx",
      "args": ["mem0-mcp-server"],
      "env": {
        "MEM0_API_KEY": "m0-...",
        "MEM0_DEFAULT_USER_ID": "your-handle"
      }
    }
  }
}
```

**Option 2: Using API key file (for CLIs that don't support env)**

```json
{
  "mcpServers": {
    "mem0": {
      "command": "uvx",
      "args": [
        "mem0-mcp-server",
        "--api-key-file=/path/to/mem0-key.txt",
        "--user-id=your-handle"
      ]
    }
  }
}
```

**Option 3: From GitHub (development)**

```json
{
  "mcpServers": {
    "mem0": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/alfonsodg/mem0-mcp.git",
        "mem0-mcp-server"
      ],
      "env": {
        "MEM0_API_KEY": "m0-...",
        "MEM0_DEFAULT_USER_ID": "your-handle"
      }
    }
  }
}
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MEM0_API_KEY` | Yes* | — | Mem0 platform API key |
| `MEM0_DEFAULT_USER_ID` | No | `mem0-mcp` | Default user_id for filters and writes |
| `MEM0_ENABLE_GRAPH_DEFAULT` | No | `false` | Enable graph memories by default |
| `MEM0_DISABLE_DNS_REBINDING_PROTECTION` | No | `false` | Disable DNS rebinding protection |
| `HOST` | No | `127.0.0.1` | Bind address (use `0.0.0.0` for containers) |
| `PORT` | No | `8081` | HTTP port |
| `LOG_FORMAT` | No | `console` | Log format: `console` or `json` |

*Required unless using `--api-key-file`.

### CLI Arguments

| Argument | Description |
|----------|-------------|
| `--api-key-file` | Path to file containing Mem0 API key |
| `--user-id` | Default user ID |
| `--api-key` | **Deprecated** — visible in process listings, use `--api-key-file` or env var |

## Docker

```bash
# Build
docker build -t mem0-mcp-server .

# Run
docker run --rm -d \
  --name mem0-mcp \
  -e MEM0_API_KEY=m0-... \
  -p 8080:8081 \
  mem0-mcp-server

# Health check
curl http://localhost:8080/health
```

## Development

```bash
git clone https://github.com/alfonsodg/mem0-mcp.git
cd mem0-mcp
cp .env.example .env  # fill in your keys
uv sync
uv run pytest
uv run ruff check src/
uv run mem0-mcp-server
```

## License

[Apache License 2.0](LICENSE) — Originally by [Mem0](https://mem0.ai), fork maintained by Alfonso de la Guarda.
