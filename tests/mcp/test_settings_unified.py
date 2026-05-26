"""Tests that Settings and MCPSettings read from the same ENVIRONMENT variable."""
import pytest
from throughball_ai.config.settings import Settings
from throughball_ai.mcp.settings import MCPSettings


def test_mcp_settings_reads_environment_var(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    s = MCPSettings()
    assert s.app_env == "staging"


def test_mcp_settings_falls_back_to_app_env(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    s = MCPSettings()
    assert s.app_env == "production"


def test_mcp_settings_and_settings_read_same_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    mcp_s = MCPSettings()
    ai_s = Settings()
    assert mcp_s.app_env == ai_s.environment


def test_mcp_settings_default_is_local(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    s = MCPSettings()
    assert s.app_env == "local"
