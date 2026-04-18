# Development Standards

Standards applied to the mem0-mcp-server project.

## Language and Runtime

- Python >= 3.10 (development on 3.14)
- Package manager: `uv` (never pip directly)
- Build system: `hatchling`

## Code Quality

- Linter/formatter: `ruff` (line-length 120)
- Lint rules: E, W, F, I, N, UP, B, S, C4, SIM, RUF
- Type checker: `mypy` (strict mode)
- Type hints: modern `X | Y` syntax, no `Optional`/`Dict` from `typing`

## Logging

- Library: `structlog`
- Format: console (dev), JSON (production via `LOG_FORMAT=json`)
- No f-strings in log calls; use keyword arguments

## Testing

- Framework: `pytest` with `pytest-cov`
- Tests import and call actual project functions
- Coverage target: >60% on core modules

## Dependencies

- MCP SDK: `mcp[cli] >= 1.6.0`
- Mem0 client: `mem0ai >= 1.0.1`
- Structured logging: `structlog >= 25.1.0`
- Validation: `pydantic` (via mcp dependency)

## Architecture

- Configuration via frozen `ServerConfig` dataclass (no global mutable state)
- Thread-safe TTL cache for `MemoryClient` instances
- All tool functions return valid JSON strings, never `None`

## Security

- Default host: `127.0.0.1` (localhost only)
- API keys via environment variables or `--api-key-file` (never CLI args in process listing)
- `.env` never tracked in git; `.env.example` provided

## Commits

- Format: Conventional Commits (`type(scope): subject`)
- Every commit references an issue (`Ref #N` or `Closes #N`)

## Container

- Multi-stage Dockerfile (builder + runtime)
- Non-root user in runtime stage
- HEALTHCHECK via `/health` endpoint
