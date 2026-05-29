"""Agent boundaries for ADK-backed implementations."""

from throughball_ai.agents.fan_gathering_adk import FanGatheringADKAgent

AGENT_NAMES = (
    "orchestrator",
    "match_analyst",
    "fan_gathering",
    "city_concierge",
    "itinerary",
)

__all__ = ["FanGatheringADKAgent", "AGENT_NAMES"]
