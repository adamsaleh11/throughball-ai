import json
from pathlib import Path

import pytest

from throughball_ai.mcp.server import build_mcp_server
from throughball_ai.mcp.tools import search_documents


async def call(mcp, tool_name: str, args: dict) -> dict:
    result = await mcp.call_tool(tool_name, args)
    return json.loads(result[0].text)


@pytest.mark.asyncio
async def test_search_documents_missing_retrieval_config_returns_degraded_empty_result(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)

    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {"query": "supporter pubs near stadium"})

    assert resp["ok"] is True
    assert resp["tool"] == "search_documents"
    assert resp["source_type"] == "none"
    assert resp["data"]["chunks"] == []
    assert resp["data"]["source_paths"] == []
    assert resp["data"]["similarity_scores"] == []
    assert resp["data"]["document_titles"] == []
    assert resp["data"]["retrieval_confidence"] == "none"
    assert resp["data"]["degraded"] is True
    assert resp["data"]["telemetry"]["failure_stage"] == "config"
    assert resp["data"]["telemetry"]["external_search_used"] is False
    assert resp["telemetry"]["degraded"] is True


@pytest.mark.asyncio
async def test_search_documents_returns_canonical_chunks_and_compatibility_results(monkeypatch):
    class FakeRetrievalService:
        def __init__(self):
            self.calls = []

        async def search(self, *, query, city_id, team_id, category, top_k, allow_external):
            self.calls.append(
                {
                    "query": query,
                    "city_id": city_id,
                    "team_id": team_id,
                    "category": category,
                    "top_k": top_k,
                    "allow_external": allow_external,
                }
            )
            return {
                "chunks": ["BMO Field has several supporter pub options nearby."],
                "source_paths": ["knowledge/seed-documents/venues/toronto-stadium-guide.md"],
                "similarity_scores": [0.83],
                "document_titles": ["Toronto Stadium Guide"],
                "retrieval_confidence": "high",
                "degraded": False,
                "telemetry": {"external_search_used": False},
                "results": [
                    {
                        "document_id": "doc_1",
                        "document_type": "venues",
                        "title": "Toronto Stadium Guide",
                        "snippet": "BMO Field has several supporter pub options nearby.",
                        "source_type": "internal",
                        "relevance_score": 0.83,
                        "created_at": None,
                    }
                ],
            }

    fake_service = FakeRetrievalService()
    search_documents.set_retrieval_service(fake_service)
    monkeypatch.setattr(search_documents, "_retrieval_configured", lambda: True)

    mcp = build_mcp_server()
    resp = await call(
        mcp,
        "search_documents",
        {
            "query": "supporter pubs near BMO Field",
            "city_id": "city_toronto",
            "team_id": "team_canada",
            "category": "venues",
            "top_k": 3,
        },
    )

    assert resp["ok"] is True
    assert resp["source_type"] == "internal"
    assert resp["data"]["chunks"] == ["BMO Field has several supporter pub options nearby."]
    assert resp["data"]["source_paths"] == ["knowledge/seed-documents/venues/toronto-stadium-guide.md"]
    assert resp["data"]["similarity_scores"] == [0.83]
    assert resp["data"]["document_titles"] == ["Toronto Stadium Guide"]
    assert resp["data"]["retrieval_confidence"] == "high"
    assert resp["data"]["degraded"] is False
    assert resp["data"]["results"][0]["snippet"] == resp["data"]["chunks"][0]
    assert fake_service.calls == [
        {
            "query": "supporter pubs near BMO Field",
            "city_id": "city_toronto",
            "team_id": "team_canada",
            "category": "venues",
            "top_k": 3,
            "allow_external": False,
        }
    ]


@pytest.mark.asyncio
async def test_search_documents_builds_default_retrieval_service_when_configured(monkeypatch):
    class FakeRetrievalService:
        async def search(self, *, query, city_id, team_id, category, top_k, allow_external):
            return {
                "chunks": ["Configured retrieval works."],
                "source_paths": ["knowledge/doc.md"],
                "similarity_scores": [0.7],
                "document_titles": ["Doc"],
                "retrieval_confidence": "medium",
                "degraded": False,
                "telemetry": {"external_search_used": False},
                "results": [],
            }

    search_documents.set_retrieval_service(None)
    monkeypatch.setenv("SUPABASE_DB_URL", "postgres://example")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setattr(
        search_documents,
        "build_default_retrieval_service",
        lambda: FakeRetrievalService(),
        raising=False,
    )

    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {"query": "configured retrieval"})

    assert resp["ok"] is True
    assert resp["source_type"] == "internal"
    assert resp["data"]["chunks"] == ["Configured retrieval works."]


def test_search_documents_tool_does_not_use_gemini_or_model_router():
    source = Path("src/throughball_ai/mcp/tools/search_documents.py").read_text(encoding="utf-8")

    assert "model_router" not in source
    assert "Gemini" not in source
    assert "gemini" not in source


@pytest.mark.asyncio
async def test_search_documents_rejects_top_k_above_cost_cap():
    mcp = build_mcp_server()
    resp = await call(mcp, "search_documents", {"query": "pubs", "top_k": 9})

    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_INPUT"
    assert resp["error"]["details"]["field"] == "top_k"
