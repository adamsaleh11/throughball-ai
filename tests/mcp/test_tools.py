import json
import pytest
from throughball_ai.mcp.server import build_mcp_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def call(mcp, tool_name: str, args: dict) -> dict:
    result = await mcp.call_tool(tool_name, args)
    return json.loads(result[0].text)


# ---------------------------------------------------------------------------
# Phase 3 — get_match_state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_match_state_returns_ok_shape():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_match_state", {"match_id": "match_123"})
    assert resp["ok"] is True
    assert resp["tool"] == "get_match_state"
    assert resp["source_type"] == "seeded"
    data = resp["data"]
    assert data["match_id"] == "match_123"
    assert "home_team_id" in data
    assert "away_team_id" in data
    assert "status" in data
    assert "minute" in data
    assert "score" in data
    assert "venue_id" in data
    assert "competition" in data
    assert "started_at" in data
    assert "last_updated_at" in data


@pytest.mark.asyncio
async def test_get_match_state_telemetry_fields_present():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_match_state", {"match_id": "match_123"})
    t = resp["telemetry"]
    for field in ("trace_id", "request_id", "latency_ms", "cache_hit",
                  "source_type", "retry_count", "degraded", "external_api_called"):
        assert field in t, f"telemetry missing: {field}"


@pytest.mark.asyncio
async def test_get_match_state_include_timeline_false_omits_timeline():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_match_state", {"match_id": "match_123", "include_timeline": False})
    assert "timeline" not in resp["data"]


@pytest.mark.asyncio
async def test_get_match_state_include_timeline_true_adds_timeline():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_match_state", {"match_id": "match_123", "include_timeline": True})
    assert isinstance(resp["data"]["timeline"], list)
    assert len(resp["data"]["timeline"]) >= 1


@pytest.mark.asyncio
async def test_get_match_state_missing_match_id_returns_invalid_input():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_match_state", {})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_INPUT"
    assert "telemetry" in resp


# ---------------------------------------------------------------------------
# Phase 4 — get_fan_hotspots
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_fan_hotspots_returns_ok_shape():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_fan_hotspots", {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "team_id": "team_usa",
    })
    assert resp["ok"] is True
    assert resp["tool"] == "get_fan_hotspots"
    assert resp["source_type"] == "seeded"
    data = resp["data"]
    assert data["city_id"] == "city_toronto"
    assert data["match_id"] == "match_123"
    assert data["team_id"] == "team_usa"
    assert isinstance(data["hotspots"], list)
    assert "computed_at" in data


@pytest.mark.asyncio
async def test_get_fan_hotspots_hotspot_fields():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_fan_hotspots", {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "team_id": "team_usa",
    })
    hotspot = resp["data"]["hotspots"][0]
    for field in ("hotspot_id", "venue_id", "name", "neighborhood",
                  "confidence", "verified_signals", "inferred_signals",
                  "score", "evidence_ids"):
        assert field in hotspot, f"hotspot missing: {field}"


@pytest.mark.asyncio
async def test_get_fan_hotspots_missing_city_id_returns_invalid_input():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_fan_hotspots", {"match_id": "match_123", "team_id": "team_usa"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Phase 4 — search_documents
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_documents_returns_ok_shape():
    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {"query": "supporter pubs near stadium"})
    assert resp["ok"] is True
    assert resp["tool"] == "search_documents"
    assert resp["source_type"] == "seeded"
    assert isinstance(resp["data"]["results"], list)


@pytest.mark.asyncio
async def test_search_documents_result_fields():
    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {"query": "supporter pubs"})
    result = resp["data"]["results"][0]
    for field in ("document_id", "document_type", "title", "snippet",
                  "source_type", "relevance_score", "created_at"):
        assert field in result, f"result missing: {field}"


@pytest.mark.asyncio
async def test_search_documents_missing_query_returns_invalid_input():
    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_search_documents_telemetry_present():
    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {"query": "pubs"})
    assert "telemetry" in resp


# ---------------------------------------------------------------------------
# All three tools listed in capabilities
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_stub_tools_registered():
    mcp = build_mcp_server()
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert "get_match_state" in names
    assert "get_fan_hotspots" in names
    assert "search_documents" in names
