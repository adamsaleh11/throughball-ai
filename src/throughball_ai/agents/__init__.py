"""Agent boundaries for ADK-backed implementations."""

from throughball_ai.agents.fan_gathering_adk import FanGatheringADKAgent
from throughball_ai.agents.itinerary_adk import ItineraryADKAgent

AGENT_NAMES = (
    "orchestrator",
    "match_analyst",
    "fan_gathering",
    "city_concierge",
    "itinerary",
)

__all__ = ["FanGatheringADKAgent", "ItineraryADKAgent", "AGENT_NAMES"]
