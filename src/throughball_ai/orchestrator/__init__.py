"""Orchestration boundary for routing, delegation, retries, and synthesis."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentCoordinator(Protocol):
    async def delegate(self, agent_name: str, request: dict) -> dict: ...
