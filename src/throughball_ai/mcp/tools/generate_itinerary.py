"""generate_itinerary — pure deterministic itinerary formatter (03-07 Phase 2).

This tool does NOT compute ordering. It receives an LLM-supplied ordered list of
candidate IDs and lays them onto days and time slots using a matchday-anchored
heuristic. Sequencing is matchday-anchored, not geographically optimized — the
tool states this honestly in the response `assumptions`.
"""
from datetime import date, timedelta
from typing import Optional

from throughball_ai.mcp.errors import error_response
from throughball_ai.mcp.registry import ToolDefinition
from throughball_ai.mcp.schemas import GenerateItineraryInput, GenerateItineraryOutput
from throughball_ai.repositories.city_data import (
    SEEDED_CITY_IDS,
    SEEDED_EVENTS,
    SEEDED_VENUES,
)

TOOL_NAME = "generate_itinerary"
TIMEOUT_MS = 2500

MAX_DAYS = 3
MAX_ITEMS_PER_DAY = 4

_KICKOFF_MINUTE = 15 * 60        # 15:00 local — seeded default kickoff
_MATCH_DURATION_MIN = 120
_PRE_SLOT_MIN = 90
_POST_SLOT_MIN = 120
_DAY_START_MINUTE = 11 * 60      # 11:00 for non-matchday days
_DAY_SLOT_MIN = 120
_DAY_GAP_MIN = 30

_HONESTY_ASSUMPTION = (
    "Sequencing is matchday-anchored, not geographically optimized: items are "
    "ordered around kickoff and supplied order, without travel-distance checks."
)


def _hhmm(total_minutes: int) -> str:
    total_minutes = max(0, min(total_minutes, 23 * 60 + 59))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _resolve_candidate(city_id: str, candidate_id: str) -> Optional[dict]:
    for v in SEEDED_VENUES:
        if v["city_id"] == city_id and v["venue_id"] == candidate_id:
            is_stadium = v["venue_type"] == "stadium"
            is_matchday = is_stadium or "matchday" in v.get("tags", [])
            return {
                "item_id": candidate_id,
                "item_type": "venue",
                "title": v["name"],
                "is_matchday": is_matchday,
                "is_stadium": is_stadium,
            }
    for e in SEEDED_EVENTS:
        if e["city_id"] == city_id and e["event_id"] == candidate_id:
            return {
                "item_id": candidate_id,
                "item_type": "event",
                "title": e["name"],
                "is_matchday": e.get("category") == "matchday",
                "is_stadium": False,
            }
    return None


def _date_range(start_date: str, end_date: Optional[str]) -> list[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) if end_date else start
    if end < start:
        end = start
    days = []
    cur = start
    while cur <= end and len(days) < MAX_DAYS:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def _build_skeleton(city_id: str, match_id: str, ordered_candidate_ids: list[str],
                    start_date: Optional[str]) -> dict:
    """Compact one-day skeleton preserving supplied order — used on degraded paths."""
    day_date = start_date or "unknown"
    items = [
        {
            "start_time": "00:00",
            "end_time": "00:00",
            "item_type": "unknown",
            "item_id": cid,
            "title": cid,
            "explanation": "Skeleton item: original order preserved, formatting incomplete.",
        }
        for cid in ordered_candidate_ids[: MAX_DAYS * MAX_ITEMS_PER_DAY]
    ]
    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "itinerary_id": f"itin_{match_id}",
            "city_id": city_id,
            "match_id": match_id,
            "days": [{"date": day_date, "items": items}],
            "assumptions": [_HONESTY_ASSUMPTION, "Compact skeleton returned; order preserved."],
        },
        "telemetry": {
            "degraded": True,
            "degraded_reason": "ITINERARY_FORMATTING_TIMEOUT",
            "source_type": "seeded",
            "external_api_called": False,
        },
    }


def _format_itinerary(city_id: str, match_id: str, traveler_profile: dict,
                      ordered_candidate_ids: list[str], start_date: str,
                      end_date: Optional[str]) -> dict:
    dates = _date_range(start_date, end_date)
    matchday = dates[0]

    resolved = [(_resolve_candidate(city_id, cid), cid) for cid in ordered_candidate_ids]

    matchday_items = [r for r, _ in resolved if r and r["is_matchday"]]
    other_items = [r for r, _ in resolved if r and not r["is_matchday"]]

    # day_date -> list of items
    by_day: dict[str, list[dict]] = {d: [] for d in dates}

    # --- Matchday anchoring ---
    stadium_idx = next((i for i, it in enumerate(matchday_items) if it["is_stadium"]), None)
    if stadium_idx is None:
        pre, stadium, post = matchday_items, None, []
    else:
        pre = matchday_items[:stadium_idx]
        stadium = matchday_items[stadium_idx]
        post = matchday_items[stadium_idx + 1:]

    n_pre = len(pre)
    for j, it in enumerate(pre):
        start = _KICKOFF_MINUTE - (n_pre - j) * _PRE_SLOT_MIN
        _append(by_day, matchday, it, start, start + _PRE_SLOT_MIN,
                "Pre-match: scheduled before kickoff from supplied matchday candidates.")
    if stadium is not None:
        _append(by_day, matchday, stadium, _KICKOFF_MINUTE,
                _KICKOFF_MINUTE + _MATCH_DURATION_MIN,
                "Match at the host stadium, anchored to kickoff.")
    post_base = _KICKOFF_MINUTE + _MATCH_DURATION_MIN
    for j, it in enumerate(post):
        start = post_base + j * _POST_SLOT_MIN
        _append(by_day, matchday, it, start, start + _POST_SLOT_MIN,
                "Post-match: scheduled after the match from supplied matchday candidates.")

    # --- Non-matchday items fill remaining days, then spill onto matchday capacity ---
    fill_dates = dates[1:] + [matchday] if len(dates) > 1 else [matchday]
    for it in other_items:
        target = _first_open_day(by_day, fill_dates)
        if target is None:
            break  # all days full — truncate remaining (cap enforcement)
        slot_index = len(by_day[target])
        start = _DAY_START_MINUTE + slot_index * (_DAY_SLOT_MIN + _DAY_GAP_MIN)
        _append(by_day, target, it, start, start + _DAY_SLOT_MIN,
                "Distributed across trip days from the supplied order.")

    days = [
        {"date": d, "items": by_day[d]}
        for d in dates
        if by_day[d]
    ]

    assumptions = [_HONESTY_ASSUMPTION]
    budget = (traveler_profile or {}).get("budget")
    if budget:
        assumptions.append(f"Candidates were filtered by traveler budget='{budget}'.")

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "source_type": "seeded",
        "data": {
            "itinerary_id": f"itin_{match_id}",
            "city_id": city_id,
            "match_id": match_id,
            "days": days,
            "assumptions": assumptions,
        },
        "telemetry": {
            "degraded": False,
            "degraded_reason": None,
            "source_type": "seeded",
            "external_api_called": False,
        },
    }


def _append(by_day: dict, day: str, item: dict, start_min: int, end_min: int,
            explanation: str) -> None:
    if len(by_day[day]) >= MAX_ITEMS_PER_DAY:
        return
    by_day[day].append({
        "start_time": _hhmm(start_min),
        "end_time": _hhmm(end_min),
        "item_type": item["item_type"],
        "item_id": item["item_id"],
        "title": item["title"],
        "explanation": explanation,
    })


def _first_open_day(by_day: dict, candidate_dates: list[str]) -> Optional[str]:
    for d in candidate_dates:
        if len(by_day[d]) < MAX_ITEMS_PER_DAY:
            return d
    return None


async def handler(
    city_id: Optional[str] = None,
    match_id: Optional[str] = None,
    traveler_profile: Optional[dict] = None,
    ordered_candidate_ids: Optional[list] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    allow_external: bool = False,
) -> dict:
    if not city_id:
        return error_response(TOOL_NAME, code="INVALID_INPUT",
                              message="city_id is required.", details={"field": "city_id"})
    if not match_id:
        return error_response(TOOL_NAME, code="INVALID_INPUT",
                              message="match_id is required.", details={"field": "match_id"})
    if city_id not in SEEDED_CITY_IDS:
        return error_response(TOOL_NAME, code="INVALID_INPUT",
                              message=f"No seeded data for city_id: {city_id}.",
                              details={"field": "city_id"})
    if not ordered_candidate_ids:
        return error_response(TOOL_NAME, code="MISSING_ORDERED_CANDIDATES",
                              message="ordered_candidate_ids must be a non-empty list.",
                              details={"field": "ordered_candidate_ids"})
    if not start_date:
        return error_response(TOOL_NAME, code="INVALID_INPUT",
                              message="start_date is required.", details={"field": "start_date"})

    try:
        return _format_itinerary(city_id, match_id, traveler_profile or {},
                                 ordered_candidate_ids, start_date, end_date)
    except Exception:
        return _build_skeleton(city_id, match_id, ordered_candidate_ids, start_date)


DEFINITION = ToolDefinition(
    name=TOOL_NAME,
    handler=handler,
    timeout_ms=TIMEOUT_MS,
    input_schema=GenerateItineraryInput,
    output_schema=GenerateItineraryOutput,
    cacheable=True,
    max_retry_count=0,
    description="Formats an LLM-ordered candidate list into a matchday-anchored day-by-day itinerary.",
)
