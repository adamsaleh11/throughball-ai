from typing import Protocol


SOURCE_TYPE = "seeded"
UPDATED_AT = "2026-05-15T00:00:00Z"

SEEDED_CITY_IDS: frozenset[str] = frozenset({"city_toronto"})


class HotspotsRepository(Protocol):
    def list_hotspots(
        self,
        *,
        city_id: str,
        match_id: str,
        team_id: str,
        limit: int,
        include_evidence: bool,
    ) -> list[dict]:
        ...


class VenuesRepository(Protocol):
    def list_venues(
        self,
        *,
        city_id: str,
        venue_type: str,
        neighborhood_id: str | None,
        limit: int,
    ) -> list[dict]:
        ...


class CityProfileRepository(Protocol):
    def get_city_profile(
        self,
        *,
        city_id: str,
        include_neighborhoods: bool,
    ) -> dict | None:
        ...


class EventsRepository(Protocol):
    def list_events(
        self,
        *,
        city_id: str,
        start_date: str | None,
        end_date: str | None,
        category: str,
        limit: int,
    ) -> list[dict]:
        ...


class InMemoryHotspotsRepository:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or SEEDED_HOTSPOTS

    def list_hotspots(
        self,
        *,
        city_id: str,
        match_id: str,
        team_id: str,
        limit: int,
        include_evidence: bool,
    ) -> list[dict]:
        rows = [
            row
            for row in self._rows
            if row["city_id"] == city_id
            and row["match_id"] == match_id
            and row["team_id"] == team_id
        ]
        if not rows:
            rows = [
                row
                for row in self._rows
                if row["city_id"] == city_id and row["team_id"] == team_id
            ]
        if not rows:
            rows = [row for row in self._rows if row["city_id"] == city_id]

        hotspots = []
        for row in rows[:limit]:
            hotspot = {
                "hotspot_id": row["hotspot_id"],
                "venue_id": row["venue_id"],
                "name": row["name"],
                "neighborhood": row["neighborhood"],
                "confidence": row["confidence"],
                "verified_signals": list(row["verified_signals"]),
                "inferred_signals": list(row["inferred_signals"]),
                "score": row["score"],
                "evidence_ids": list(row["evidence_ids"]) if include_evidence else [],
            }
            hotspots.append(hotspot)
        return hotspots


class InMemoryVenuesRepository:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or SEEDED_VENUES

    def list_venues(
        self,
        *,
        city_id: str,
        venue_type: str,
        neighborhood_id: str | None,
        limit: int,
    ) -> list[dict]:
        rows = [row for row in self._rows if row["city_id"] == city_id]
        if venue_type != "any":
            rows = [row for row in rows if row["venue_type"] == venue_type]
        if neighborhood_id:
            rows = [row for row in rows if row["neighborhood_id"] == neighborhood_id]
        return [_without_internal_fields(row) for row in rows[:limit]]


class InMemoryCityProfileRepository:
    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self._rows = rows or SEEDED_CITY_PROFILES

    def get_city_profile(
        self,
        *,
        city_id: str,
        include_neighborhoods: bool,
    ) -> dict | None:
        row = self._rows.get(city_id)
        if row is None:
            return None
        profile = dict(row)
        profile["neighborhoods"] = (
            [dict(neighborhood) for neighborhood in row["neighborhoods"]]
            if include_neighborhoods
            else []
        )
        return profile


class InMemoryEventsRepository:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or SEEDED_EVENTS

    def list_events(
        self,
        *,
        city_id: str,
        start_date: str | None,
        end_date: str | None,
        category: str,
        limit: int,
    ) -> list[dict]:
        rows = [row for row in self._rows if row["city_id"] == city_id]
        if category != "any":
            rows = [row for row in rows if row["category"] == category]
        if start_date:
            rows = [row for row in rows if row["starts_at"][:10] >= start_date]
        if end_date:
            rows = [row for row in rows if row["starts_at"][:10] <= end_date]
        return [_without_internal_fields(row) for row in rows[:limit]]


def aggregate_signals(items: list[dict]) -> tuple[list[str], list[str]]:
    verified: list[str] = []
    inferred: list[str] = []
    for item in items:
        verified.extend(item.get("verified_signals", []))
        inferred.extend(item.get("inferred_signals", []))
    return _dedupe(verified), _dedupe(inferred)


def confidence_metadata(items: list[dict], *, empty_reason: str) -> dict:
    if not items:
        return {
            "level": "none",
            "reason": empty_reason,
        }
    levels = [item.get("confidence") for item in items]
    if "high" in levels:
        level = "high"
    elif "medium" in levels:
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "item_count": len(items),
        "reason": "Seeded data from curated Throughball records.",
    }


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _without_internal_fields(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "city_id"}


SEEDED_VENUES = [
    {
        "city_id": "city_toronto",
        "venue_id": "venue_bmo_field",
        "name": "BMO Field",
        "venue_type": "stadium",
        "neighborhood_id": "nb_exhibition_place",
        "address": "170 Princes' Blvd",
        "geo": {"lat": 43.6332, "lng": -79.4186},
        "tags": ["stadium", "matchday", "transit"],
        "source_type": SOURCE_TYPE,
        "confidence": "high",
        "verified_signals": ["Official host stadium listing"],
        "inferred_signals": ["Matchday crowd activity concentrates around venue approaches"],
        "last_updated_at": UPDATED_AT,
    },
    {
        "city_id": "city_toronto",
        "venue_id": "venue_pub_1",
        "name": "Example Supporters Pub",
        "venue_type": "pub",
        "neighborhood_id": "nb_king_west",
        "address": "123 Example St",
        "geo": {"lat": 43.6426, "lng": -79.3871},
        "tags": ["supporters", "late-night", "watch-party"],
        "source_type": SOURCE_TYPE,
        "confidence": "medium",
        "verified_signals": ["Partner venue listing"],
        "inferred_signals": ["Near downtown hotel and stadium transit corridors"],
        "last_updated_at": UPDATED_AT,
    },
    {
        "city_id": "city_toronto",
        "venue_id": "venue_fanzone_1",
        "name": "Example Matchday Fan Zone",
        "venue_type": "attraction",
        "neighborhood_id": "nb_downtown",
        "address": "456 Example Ave",
        "geo": {"lat": 43.6410, "lng": -79.3890},
        "tags": ["fan-zone", "matchday", "families"],
        "source_type": SOURCE_TYPE,
        "confidence": "medium",
        "verified_signals": ["Seeded matchday fan-zone listing"],
        "inferred_signals": ["Central location is likely to draw mixed supporter traffic"],
        "last_updated_at": UPDATED_AT,
    },
]


SEEDED_EVENTS = [
    {
        "city_id": "city_toronto",
        "event_id": "event_matchday_1",
        "name": "Example Matchday Fan Zone",
        "category": "matchday",
        "starts_at": "2026-06-18T18:00:00-04:00",
        "ends_at": "2026-06-18T23:30:00-04:00",
        "venue_id": "venue_fanzone_1",
        "source_type": SOURCE_TYPE,
        "confidence": "medium",
        "verified_signals": ["Seeded matchday event listing"],
        "inferred_signals": ["Event timing overlaps pre-match supporter movement"],
    },
    {
        "city_id": "city_toronto",
        "event_id": "event_pub_1",
        "name": "Example Supporters Pub Watch Party",
        "category": "matchday",
        "starts_at": "2026-06-18T19:00:00-04:00",
        "ends_at": "2026-06-18T22:00:00-04:00",
        "venue_id": "venue_pub_1",
        "source_type": SOURCE_TYPE,
        "confidence": "medium",
        "verified_signals": ["Seeded watch-party listing"],
        "inferred_signals": ["Supporter venue tags indicate likely pre-match crowd"],
    },
]


SEEDED_HOTSPOTS = [
    {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "team_id": "team_usa",
        "hotspot_id": "hotspot_1",
        "venue_id": "venue_pub_1",
        "name": "Example Supporters Pub",
        "neighborhood": "King West",
        "confidence": "medium",
        "verified_signals": ["Partner venue listing"],
        "inferred_signals": ["Near stadium transit corridor"],
        "score": 0.78,
        "evidence_ids": ["doc_123"],
        "computed_at": "2026-06-18T16:00:00Z",
    },
    {
        "city_id": "city_toronto",
        "match_id": "match_123",
        "team_id": "team_canada",
        "hotspot_id": "hotspot_2",
        "venue_id": "venue_fanzone_1",
        "name": "Example Matchday Fan Zone",
        "neighborhood": "Downtown",
        "confidence": "medium",
        "verified_signals": ["Seeded matchday fan-zone listing"],
        "inferred_signals": ["Central transit access supports mixed supporter turnout"],
        "score": 0.72,
        "evidence_ids": ["doc_124"],
        "computed_at": "2026-06-18T16:00:00Z",
    },
]


SEEDED_CITY_PROFILES = {
    "city_toronto": {
        "city_id": "city_toronto",
        "name": "Toronto",
        "country_code": "CAN",
        "country": "Canada",
        "timezone": "America/Toronto",
        "summary": "Large multicultural host city with dense downtown transit coverage.",
        "neighborhoods": [
            {
                "neighborhood_id": "nb_king_west",
                "name": "King West",
                "summary": "Nightlife-heavy district near downtown hotels.",
            },
            {
                "neighborhood_id": "nb_downtown",
                "name": "Downtown",
                "summary": "Central hotel, dining, and transit district.",
            },
            {
                "neighborhood_id": "nb_exhibition_place",
                "name": "Exhibition Place",
                "summary": "Stadium-adjacent matchday district near BMO Field.",
            },
        ],
        "transit_summary": "Subway, streetcar, commuter rail, and rideshare coverage.",
        "transport_notes": ["Use downtown transit corridors on matchday."],
        "matchday_notes": ["Fan zones and supporter pubs may be busy before kickoff."],
        "safety_notes": ["Use official routes and verify hours before travel."],
        "verified_signals": ["Seeded host city profile"],
        "inferred_signals": ["Tourist and stadium district summaries indicate downtown crowding"],
        "confidence": "medium",
        "last_updated_at": UPDATED_AT,
    }
}

