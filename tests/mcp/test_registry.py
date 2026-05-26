"""Tests for ToolDefinition validation and registry auto-discovery."""
import pytest
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.server import _build_registry
from throughball_ai.mcp.tools import get_match_state, get_fan_hotspots, search_documents


# ---------------------------------------------------------------------------
# ToolDefinition.validate()
# ---------------------------------------------------------------------------

async def _noop(**_kwargs) -> dict:
    return {"ok": True}


def test_valid_definition_does_not_raise():
    defn = ToolDefinition(name="my_tool", handler=_noop, timeout_ms=1000)
    defn.validate()  # must not raise


def test_validate_rejects_empty_name():
    defn = ToolDefinition(name="", handler=_noop, timeout_ms=1000)
    with pytest.raises(ValueError, match="name"):
        defn.validate()


def test_validate_rejects_zero_timeout():
    defn = ToolDefinition(name="my_tool", handler=_noop, timeout_ms=0)
    with pytest.raises(ValueError, match="timeout_ms"):
        defn.validate()


def test_validate_rejects_negative_timeout():
    defn = ToolDefinition(name="my_tool", handler=_noop, timeout_ms=-1)
    with pytest.raises(ValueError, match="timeout_ms"):
        defn.validate()


def test_validate_rejects_negative_retry_count():
    defn = ToolDefinition(name="my_tool", handler=_noop, timeout_ms=1000, max_retry_count=-1)
    with pytest.raises(ValueError, match="max_retry_count"):
        defn.validate()


def test_validate_rejects_non_callable_handler():
    defn = ToolDefinition(name="my_tool", handler="not_a_function", timeout_ms=1000)
    with pytest.raises(ValueError, match="handler"):
        defn.validate()


# ---------------------------------------------------------------------------
# Tool DEFINITION constants
# ---------------------------------------------------------------------------

def test_each_tool_module_exposes_definition():
    for module in [get_match_state, get_fan_hotspots, search_documents]:
        assert hasattr(module, "DEFINITION"), f"{module.__name__} missing DEFINITION"
        assert isinstance(module.DEFINITION, ToolDefinition)


def test_tool_definitions_are_valid():
    for module in [get_match_state, get_fan_hotspots, search_documents]:
        module.DEFINITION.validate()  # must not raise


def test_tool_definition_name_matches_tool_name_constant():
    for module in [get_match_state, get_fan_hotspots, search_documents]:
        assert module.DEFINITION.name == module.TOOL_NAME


def test_tool_definition_handler_is_module_handler():
    for module in [get_match_state, get_fan_hotspots, search_documents]:
        assert module.DEFINITION.handler is module.handler


# ---------------------------------------------------------------------------
# _build_registry()
# ---------------------------------------------------------------------------

def test_build_registry_returns_all_three_tools():
    registry = _build_registry()
    assert set(registry.keys()) == {"get_match_state", "get_fan_hotspots", "search_documents"}


def test_build_registry_keys_match_definition_names():
    registry = _build_registry()
    for key, defn in registry.items():
        assert key == defn.name
