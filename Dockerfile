# Build stage
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
WORKDIR /build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml README.md ./
COPY src ./src

RUN uv pip install --system --no-cache .

# Runtime stage
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/mem0-mcp-server /usr/local/bin/ 2>/dev/null || true
COPY src ./src

RUN useradd --create-home --shell /bin/bash appuser
USER appuser

ENV HOST=0.0.0.0
ENV PORT=8081

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')" || exit 1

CMD ["python", "-m", "mem0_mcp_server.http_entry"]
