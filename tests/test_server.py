"""Tests for mem0_mcp_server core logic."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mem0_mcp_server.server import (
    ServerConfig,
    _default_enable_graph,
    _mem0_call,
    _mem0_client,
    _with_default_filters,
    clear_client_cache,
    create_server,
)

# ---------------------------------------------------------------------------
# _with_default_filters
# ---------------------------------------------------------------------------


class TestWithDefaultFilters:
    def test_none_filters(self):
        assert _with_default_filters("u1", None) == {"AND": [{"user_id": "u1"}]}

    def test_empty_dict(self):
        assert _with_default_filters("u1", {}) == {"AND": [{"user_id": "u1"}]}

    def test_simple_filter_wrapped(self):
        result = _with_default_filters("u1", {"status": "active"})
        assert "AND" in result
        assert {"user_id": "u1"} in result["AND"]

    def test_existing_user_not_duplicated(self):
        filters = {"AND": [{"user_id": "other"}]}
        result = _with_default_filters("u1", filters)
        user_ids = [f.get("user_id") for f in result["AND"] if "user_id" in f]
        assert len(user_ids) == 1
        assert user_ids[0] == "other"

    def test_or_filter_gets_user(self):
        filters = {"OR": [{"status": "active"}]}
        result = _with_default_filters("u1", filters)
        assert {"user_id": "u1"} in result.get("AND", [])

    def test_invalid_and_type_raises(self):
        with pytest.raises(ValueError, match="must be a list"):
            _with_default_filters("u1", {"AND": "not-a-list"})


# ---------------------------------------------------------------------------
# _mem0_call
# ---------------------------------------------------------------------------


class TestMem0Call:
    def test_success_returns_json(self):
        mock_fn = MagicMock(return_value={"key": "value"})
        result = _mem0_call(mock_fn)
        assert json.loads(result) == {"key": "value"}

    def test_never_returns_none(self):
        mock_fn = MagicMock(side_effect=RuntimeError("boom"))
        result = _mem0_call(mock_fn)
        assert result is not None
        parsed = json.loads(result)
        assert "error" in parsed
        assert "boom" in parsed["error"]

    def test_retries_on_5xx(self):
        exc = Exception("server error")
        exc.status = 502  # type: ignore[attr-defined]
        mock_fn = MagicMock(side_effect=exc)
        with patch("mem0_mcp_server.server.time.sleep"):
            result = _mem0_call(mock_fn)
        assert mock_fn.call_count == 3
        assert "error" in json.loads(result)

    def test_no_retry_on_4xx(self):
        exc = Exception("not found")
        exc.status = 404  # type: ignore[attr-defined]
        mock_fn = MagicMock(side_effect=exc)
        result = _mem0_call(mock_fn)
        assert mock_fn.call_count == 1
        assert "error" in json.loads(result)

    def test_handles_none_result(self):
        mock_fn = MagicMock(return_value=None)
        result = _mem0_call(mock_fn)
        assert result == "null"


# ---------------------------------------------------------------------------
# _mem0_client
# ---------------------------------------------------------------------------


class TestMem0Client:
    def setup_method(self):
        clear_client_cache()

    def test_invalid_prefix_raises(self):
        with pytest.raises(ValueError, match="Invalid MEM0_API_KEY"):
            _mem0_client("invalid-key")

    def test_short_key_raises(self):
        with pytest.raises(ValueError, match="Invalid MEM0_API_KEY"):
            _mem0_client("m0-short")

    @patch("mem0_mcp_server.server.MemoryClient")
    def test_caches_client(self, mock_cls):
        mock_cls.return_value = MagicMock()
        c1 = _mem0_client("m0-valid-key-12345")
        c2 = _mem0_client("m0-valid-key-12345")
        assert c1 is c2
        assert mock_cls.call_count == 1

    @patch("mem0_mcp_server.server.MemoryClient")
    def test_different_keys_different_clients(self, mock_cls):
        mock_cls.return_value = MagicMock()
        _mem0_client("m0-key-aaaaaaa")
        _mem0_client("m0-key-bbbbbbb")
        assert mock_cls.call_count == 2


# ---------------------------------------------------------------------------
# _default_enable_graph
# ---------------------------------------------------------------------------


class TestDefaultEnableGraph:
    def test_explicit_true(self):
        assert _default_enable_graph(True, False) is True

    def test_explicit_false(self):
        assert _default_enable_graph(False, True) is False

    def test_none_uses_default_true(self):
        assert _default_enable_graph(None, True) is True

    def test_none_uses_default_false(self):
        assert _default_enable_graph(None, False) is False


# ---------------------------------------------------------------------------
# ServerConfig
# ---------------------------------------------------------------------------


class TestServerConfig:
    def test_defaults(self):
        cfg = ServerConfig()
        assert cfg.api_key is None
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8081
        assert cfg.enable_graph_default is False

    def test_frozen(self):
        cfg = ServerConfig()
        with pytest.raises(AttributeError):
            cfg.api_key = "test"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# create_server
# ---------------------------------------------------------------------------


class TestCreateServer:
    def test_returns_fastmcp(self):
        server = create_server()
        assert server is not None
        assert server.name == "mem0"
