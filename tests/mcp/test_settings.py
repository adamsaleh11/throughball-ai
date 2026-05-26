import pytest
from throughball_ai.mcp.settings import MCPSettings


def test_settings_load_defaults():
    s = MCPSettings()
    assert s.ai_api_host == "127.0.0.1"
    assert s.ai_api_port == 8001
    assert s.max_tool_calls_per_request == 5


def test_settings_max_tool_calls_overridable(monkeypatch):
    monkeypatch.setenv("MAX_TOOL_CALLS_PER_REQUEST", "10")
    s = MCPSettings()
    assert s.max_tool_calls_per_request == 10


def test_settings_host_port_overridable(monkeypatch):
    monkeypatch.setenv("AI_API_HOST", "0.0.0.0")
    monkeypatch.setenv("AI_API_PORT", "9000")
    s = MCPSettings()
    assert s.ai_api_host == "0.0.0.0"
    assert s.ai_api_port == 9000
