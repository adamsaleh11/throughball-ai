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
async def test_search_documents_returns_ok_shape(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)

    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {"query": "supporter pubs near stadium"})
    assert resp["ok"] is True
    assert resp["tool"] == "search_documents"
    assert resp["source_type"] == "none"
    assert resp["data"]["retrieval_confidence"] == "none"
    assert resp["data"]["degraded"] is True
    assert isinstance(resp["data"]["results"], list)


@pytest.mark.asyncio
async def test_search_documents_result_fields(monkeypatch):
    from throughball_ai.mcp.tools import search_documents

    class FakeRetrievalService:
        async def search(self, **_kwargs):
            return {
                "chunks": ["Supporter pub evidence."],
                "source_paths": ["knowledge/doc.md"],
                "similarity_scores": [0.8],
                "document_titles": ["Doc"],
                "retrieval_confidence": "high",
                "degraded": False,
                "telemetry": {"external_search_used": False},
                "results": [
                    {
                        "document_id": "doc_1",
                        "document_type": "venues",
                        "title": "Doc",
                        "snippet": "Supporter pub evidence.",
                        "source_type": "internal",
                        "relevance_score": 0.8,
                        "created_at": None,
                    }
                ],
            }

    search_documents.set_retrieval_service(FakeRetrievalService())
    monkeypatch.setattr(search_documents, "_retrieval_configured", lambda: True)
    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {"query": "supporter pubs"})
    result = resp["data"]["results"][0]
    for field in ("document_id", "document_type", "title", "snippet",
                  "source_type", "relevance_score", "created_at"):
        assert field in result, f"result missing: {field}"
    search_documents.set_retrieval_service(None)


@pytest.mark.asyncio
async def test_search_documents_missing_query_returns_invalid_input():
    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_search_documents_invalid_limit_returns_invalid_input():
    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {"query": "pubs", "limit": 0})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_INPUT"
    assert resp["error"]["details"]["field"] == "limit"


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
    assert "get_city_events" in names
    assert "get_venues" in names
    assert "search_documents" in names
    assert "get_team_profile" in names
    assert "get_city_profile" in names


@pytest.mark.asyncio
async def test_all_tools_return_declared_output_schema_shapes(monkeypatch):
    from throughball_ai.mcp.server import _build_registry
    from throughball_ai.mcp.tools import search_documents

    search_documents.set_retrieval_service(None)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)

    mcp = build_mcp_server()
    registry = _build_registry()
    calls = {
        "get_match_state": {"match_id": "match_123"},
        "get_fan_hotspots": {
            "city_id": "city_toronto",
            "match_id": "match_123",
            "team_id": "team_usa",
        },
        "get_city_events": {"city_id": "city_toronto"},
        "get_venues": {"city_id": "city_toronto"},
        "search_documents": {"query": "supporter pubs"},
        "get_team_profile": {"team_id": "team_argentina"},
        "get_city_profile": {"city_id": "city_toronto"},
        "get_route_context": {
            "city_id": "city_toronto",
            "origin": {"type": "venue", "id": "venue_pub_1"},
            "destination": {"type": "venue", "id": "venue_bmo_field"},
            "mode": "transit",
        },
        "generate_itinerary": {
            "city_id": "city_toronto",
            "match_id": "match_123",
            "ordered_candidate_ids": ["venue_bmo_field"],
            "start_date": "2026-06-18",
        },
    }

    for tool_name, args in calls.items():
        resp = await call(mcp, tool_name, args)
        registry[tool_name].output_schema.model_validate(resp)


@pytest.mark.asyncio
async def test_get_city_events_returns_seeded_matchday_events():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_city_events", {
        "city_id": "city_toronto",
        "category": "matchday",
    })
    assert resp["ok"] is True
    assert resp["tool"] == "get_city_events"
    assert resp["source_type"] == "seeded"
    assert resp["telemetry"]["external_api_called"] is False
    event = resp["data"]["events"][0]
    for field in ("event_id", "name", "category", "starts_at", "ends_at",
                  "venue_id", "source_type", "confidence"):
        assert field in event, f"event missing: {field}"


@pytest.mark.asyncio
async def test_get_venues_returns_seeded_supporter_venues():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_venues", {
        "city_id": "city_toronto",
        "venue_type": "pub",
    })
    assert resp["ok"] is True
    assert resp["tool"] == "get_venues"
    assert resp["source_type"] == "seeded"
    assert resp["telemetry"]["external_api_called"] is False
    venue = resp["data"]["venues"][0]
    for field in ("venue_id", "name", "venue_type", "neighborhood_id",
                  "address", "geo", "tags", "source_type", "last_updated_at"):
        assert field in venue, f"venue missing: {field}"


@pytest.mark.asyncio
async def test_new_fan_tools_missing_city_id_returns_invalid_input():
    mcp = build_mcp_server()

    events_resp = await call(mcp, "get_city_events", {})
    venues_resp = await call(mcp, "get_venues", {})

    assert events_resp["ok"] is False
    assert events_resp["error"]["code"] == "INVALID_INPUT"
    assert venues_resp["ok"] is False
    assert venues_resp["error"]["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_get_team_profile_returns_seeded_context():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_team_profile", {"team_id": "team_argentina"})
    assert resp["ok"] is True
    assert resp["tool"] == "get_team_profile"
    assert resp["source_type"] == "seeded"
    assert resp["telemetry"]["external_api_called"] is False
    data = resp["data"]
    for field in ("team_id", "name", "country", "aliases", "supporter_notes",
                  "rivalries", "known_supporter_areas", "evidence_ids",
                  "last_updated_at"):
        assert field in data, f"team profile missing: {field}"


@pytest.mark.asyncio
async def test_get_city_profile_returns_seeded_context():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_city_profile", {"city_id": "city_toronto"})
    assert resp["ok"] is True
    assert resp["tool"] == "get_city_profile"
    assert resp["source_type"] == "seeded"
    assert resp["telemetry"]["external_api_called"] is False
    data = resp["data"]
    for field in ("city_id", "name", "country", "timezone", "neighborhoods",
                  "transport_notes", "matchday_notes", "safety_notes",
                  "last_updated_at"):
        assert field in data, f"city profile missing: {field}"


@pytest.mark.asyncio
async def test_profile_tools_missing_required_ids_return_invalid_input():
    mcp = build_mcp_server()
    team_resp = await call(mcp, "get_team_profile", {})
    city_resp = await call(mcp, "get_city_profile", {})
    assert team_resp["ok"] is False
    assert team_resp["error"]["code"] == "INVALID_INPUT"
    assert city_resp["ok"] is False
    assert city_resp["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# 07-03 — item-level signal provenance in venue and event records
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_venues_item_records_include_signal_provenance():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_venues", {"city_id": "city_toronto"})
    assert resp["ok"] is True
    venue = resp["data"]["venues"][0]
    assert "verified_signals" in venue, "venue record missing verified_signals provenance"
    assert "inferred_signals" in venue, "venue record missing inferred_signals provenance"
    assert isinstance(venue["verified_signals"], list)
    assert isinstance(venue["inferred_signals"], list)


@pytest.mark.asyncio
async def test_get_venues_top_level_signals_are_deduped_aggregate():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_venues", {"city_id": "city_toronto"})
    assert resp["ok"] is True
    data = resp["data"]
    assert "verified_signals" in data, "top-level verified_signals missing"
    assert "inferred_signals" in data, "top-level inferred_signals missing"
    assert len(data["verified_signals"]) > 0, "expected at least one top-level verified signal"
    assert len(data["inferred_signals"]) > 0, "expected at least one top-level inferred signal"


@pytest.mark.asyncio
async def test_get_city_events_item_records_include_signal_provenance():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_city_events", {"city_id": "city_toronto", "category": "matchday"})
    assert resp["ok"] is True
    event = resp["data"]["events"][0]
    assert "verified_signals" in event, "event record missing verified_signals provenance"
    assert "inferred_signals" in event, "event record missing inferred_signals provenance"
    assert isinstance(event["verified_signals"], list)
    assert isinstance(event["inferred_signals"], list)
    data = resp["data"]
    assert len(data["verified_signals"]) > 0, "expected non-empty top-level verified signals"
    assert len(data["inferred_signals"]) > 0, "expected non-empty top-level inferred signals"


# ---------------------------------------------------------------------------
# 07-03 — smoke test: get_venues through public MCP boundary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_venues_smoke_toronto_seeded_with_verified_signals():
    """Manual smoke-test path: call get_venues through the MCP boundary the same way
    ADK agents do, and confirm source_type is seeded and venue records carry signals."""
    mcp = build_mcp_server()
    resp = await call(mcp, "get_venues", {"city_id": "city_toronto"})
    assert resp["ok"] is True
    assert resp["source_type"] == "seeded"
    venue = resp["data"]["venues"][0]
    assert len(venue["verified_signals"]) > 0, "venue missing at least one verified signal"


# ---------------------------------------------------------------------------
# 07-03 — unknown city_id returns CITY_NOT_FOUND, not degraded empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_venues_unknown_city_returns_city_not_found():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_venues", {"city_id": "city_unknown_xyz"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "CITY_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_city_events_unknown_city_returns_city_not_found():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_city_events", {"city_id": "city_unknown_xyz"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "CITY_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_fan_hotspots_unknown_city_returns_city_not_found():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_fan_hotspots", {
        "city_id": "city_unknown_xyz",
        "match_id": "match_123",
        "team_id": "team_usa",
    })
    assert resp["ok"] is False
    assert resp["error"]["code"] == "CITY_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_city_profile_unknown_city_returns_city_not_found():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_city_profile", {"city_id": "city_unknown_xyz"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "CITY_NOT_FOUND"


# ---------------------------------------------------------------------------
# 07-03 — valid filters with no matching data return degraded empty, not errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_venues_no_match_filter_returns_degraded_empty():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_venues", {
        "city_id": "city_toronto",
        "venue_type": "nonexistent_type",
    })
    assert resp["ok"] is True
    assert resp["data"]["venues"] == []
    assert resp["telemetry"]["degraded"] is True
    assert resp["telemetry"]["degraded_reason"] is not None


@pytest.mark.asyncio
async def test_get_city_events_no_match_filter_returns_degraded_empty():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_city_events", {
        "city_id": "city_toronto",
        "category": "nonexistent_category",
    })
    assert resp["ok"] is True
    assert resp["data"]["events"] == []
    assert resp["telemetry"]["degraded"] is True
    assert resp["telemetry"]["degraded_reason"] is not None


# ---------------------------------------------------------------------------
# 03-07 Phase 1 — get_route_context
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_route_context_seeded_pair_returns_ok_shape():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_route_context", {
        "city_id": "city_toronto",
        "origin": {"type": "venue", "id": "venue_pub_1"},
        "destination": {"type": "venue", "id": "venue_bmo_field"},
        "mode": "transit",
    })
    assert resp["ok"] is True
    assert resp["tool"] == "get_route_context"
    assert resp["source_type"] == "seeded"
    assert resp["telemetry"]["external_api_called"] is False
    data = resp["data"]
    assert data["city_id"] == "city_toronto"
    assert data["origin_id"] == "venue_pub_1"
    assert data["destination_id"] == "venue_bmo_field"
    assert data["mode"] == "transit"
    assert isinstance(data["estimated_duration_minutes"], int)
    assert isinstance(data["distance_km"], (int, float))
    assert isinstance(data["route_summary"], str) and data["route_summary"]
    assert data["confidence"] in ("low", "medium", "high")
    assert "computed_at" in data


@pytest.mark.asyncio
async def test_get_route_context_reverse_pair_resolves_same_route():
    mcp = build_mcp_server()
    forward = await call(mcp, "get_route_context", {
        "city_id": "city_toronto",
        "origin": {"type": "venue", "id": "venue_pub_1"},
        "destination": {"type": "venue", "id": "venue_bmo_field"},
        "mode": "transit",
    })
    reverse = await call(mcp, "get_route_context", {
        "city_id": "city_toronto",
        "origin": {"type": "venue", "id": "venue_bmo_field"},
        "destination": {"type": "venue", "id": "venue_pub_1"},
        "mode": "transit",
    })
    assert reverse["ok"] is True
    assert reverse["data"]["estimated_duration_minutes"] == forward["data"]["estimated_duration_minutes"]
    assert reverse["data"]["distance_km"] == forward["data"]["distance_km"]
    assert reverse["data"]["origin_id"] == "venue_bmo_field"
    assert reverse["data"]["destination_id"] == "venue_pub_1"


@pytest.mark.asyncio
async def test_get_route_context_unknown_pair_degrades_to_static():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_route_context", {
        "city_id": "city_toronto",
        "origin": {"type": "venue", "id": "venue_pub_1"},
        "destination": {"type": "venue", "id": "venue_fanzone_1"},
        "mode": "transit",
    })
    assert resp["ok"] is True
    assert resp["telemetry"]["degraded"] is True
    assert resp["telemetry"]["degraded_reason"] == "POINT_TO_POINT_ROUTE_UNAVAILABLE"
    assert resp["data"]["confidence"] == "low"
    assert resp["data"]["estimated_duration_minutes"] is None


@pytest.mark.asyncio
async def test_get_route_context_any_mode_resolves_to_transit():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_route_context", {
        "city_id": "city_toronto",
        "origin": {"type": "venue", "id": "venue_pub_1"},
        "destination": {"type": "venue", "id": "venue_bmo_field"},
        "mode": "any",
    })
    assert resp["ok"] is True
    assert resp["data"]["mode"] == "transit"


@pytest.mark.asyncio
async def test_get_route_context_missing_points_returns_invalid_input():
    mcp = build_mcp_server()
    no_city = await call(mcp, "get_route_context", {
        "origin": {"type": "venue", "id": "venue_pub_1"},
        "destination": {"type": "venue", "id": "venue_bmo_field"},
    })
    assert no_city["ok"] is False
    assert no_city["error"]["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_get_route_context_invalid_mode_returns_invalid_input():
    mcp = build_mcp_server()
    resp = await call(mcp, "get_route_context", {
        "city_id": "city_toronto",
        "origin": {"type": "venue", "id": "venue_pub_1"},
        "destination": {"type": "venue", "id": "venue_bmo_field"},
        "mode": "teleport",
    })
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_get_route_context_registered():
    mcp = build_mcp_server()
    tools = await mcp.list_tools()
    assert "get_route_context" in {t.name for t in tools}


# ---------------------------------------------------------------------------
# 03-07 Phase 2 — generate_itinerary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_itinerary_returns_day_structured_items():
    mcp = build_mcp_server()
    resp = await call(mcp, "generate_itinerary", {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "traveler_profile": {"party_size": 2, "budget": "medium", "interests": ["supporter pubs"]},
        "ordered_candidate_ids": ["venue_pub_1", "venue_bmo_field"],
        "start_date": "2026-06-18",
        "end_date": "2026-06-20",
    })
    assert resp["ok"] is True
    assert resp["tool"] == "generate_itinerary"
    assert resp["source_type"] == "seeded"
    assert resp["telemetry"]["external_api_called"] is False
    data = resp["data"]
    assert data["city_id"] == "city_toronto"
    assert data["match_id"] == "match_123"
    assert isinstance(data["days"], list) and len(data["days"]) >= 1
    day = data["days"][0]
    assert "date" in day and isinstance(day["items"], list)
    item = day["items"][0]
    for field in ("start_time", "end_time", "item_type", "item_id", "title", "explanation"):
        assert field in item, f"item missing: {field}"
    assert isinstance(data["assumptions"], list) and len(data["assumptions"]) >= 1


@pytest.mark.asyncio
async def test_generate_itinerary_anchors_stadium_to_kickoff():
    mcp = build_mcp_server()
    resp = await call(mcp, "generate_itinerary", {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "ordered_candidate_ids": ["venue_fanzone_1", "venue_bmo_field"],
        "start_date": "2026-06-18",
        "end_date": "2026-06-20",
    })
    matchday = next(d for d in resp["data"]["days"] if d["date"] == "2026-06-18")
    stadium_item = next(i for i in matchday["items"] if i["item_id"] == "venue_bmo_field")
    assert stadium_item["start_time"] == "15:00"
    # Fan zone (matchday-tagged) is placed before kickoff on the same day.
    fanzone_item = next(i for i in matchday["items"] if i["item_id"] == "venue_fanzone_1")
    assert fanzone_item["end_time"] <= "15:00"


@pytest.mark.asyncio
async def test_generate_itinerary_enforces_caps():
    mcp = build_mcp_server()
    resp = await call(mcp, "generate_itinerary", {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "ordered_candidate_ids": ["venue_pub_1"] * 13,
        "start_date": "2026-06-18",
        "end_date": "2026-06-20",
    })
    days = resp["data"]["days"]
    assert len(days) <= 3
    total = sum(len(d["items"]) for d in days)
    assert total <= 12
    assert all(len(d["items"]) <= 4 for d in days)


@pytest.mark.asyncio
async def test_generate_itinerary_empty_candidates_returns_missing_error():
    mcp = build_mcp_server()
    resp = await call(mcp, "generate_itinerary", {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "ordered_candidate_ids": [],
        "start_date": "2026-06-18",
    })
    assert resp["ok"] is False
    assert resp["error"]["code"] == "MISSING_ORDERED_CANDIDATES"


@pytest.mark.asyncio
async def test_generate_itinerary_fewer_candidates_yields_fewer_days_no_empty():
    mcp = build_mcp_server()
    resp = await call(mcp, "generate_itinerary", {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "ordered_candidate_ids": ["venue_bmo_field"],
        "start_date": "2026-06-18",
        "end_date": "2026-06-20",
    })
    days = resp["data"]["days"]
    assert len(days) == 1
    assert all(len(d["items"]) >= 1 for d in days)


@pytest.mark.asyncio
async def test_generate_itinerary_formatting_failure_returns_skeleton():
    mcp = build_mcp_server()
    resp = await call(mcp, "generate_itinerary", {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "ordered_candidate_ids": ["venue_pub_1", "venue_bmo_field"],
        "start_date": "not-a-real-date",
    })
    assert resp["ok"] is True
    assert resp["telemetry"]["degraded"] is True
    assert resp["telemetry"]["degraded_reason"] == "ITINERARY_FORMATTING_TIMEOUT"
    # Skeleton preserves supplied order.
    ids = [i["item_id"] for d in resp["data"]["days"] for i in d["items"]]
    assert ids == ["venue_pub_1", "venue_bmo_field"]


@pytest.mark.asyncio
async def test_generate_itinerary_registered():
    mcp = build_mcp_server()
    tools = await mcp.list_tools()
    assert "generate_itinerary" in {t.name for t in tools}


