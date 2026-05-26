# MCP Tool Contracts

These contracts define the MCP tool surface for `throughball-ai`. The system is orchestration-first and cost-aware: tools should prefer Supabase or local cached data, avoid live external calls by default, and return degraded responses instead of forcing expensive retry loops.

## Shared Rules

### Source Types

Every successful tool response MUST include `source_type` with one of:

- `seeded`: shipped or preloaded static data
- `cached`: Supabase/local cached data
- `user_generated`: user-provided or creator-authored data
- `external`: live external API data

### Standard Error Schema

All tools return the same error shape when `ok` is `false`.

```json
{
  "ok": false,
  "tool": "get_match_state",
  "error": {
    "code": "DATA_UNAVAILABLE",
    "message": "Match state was not found in cached data.",
    "retryable": false,
    "degraded_available": true,
    "details": {
      "match_id": "match_123"
    }
  },
  "telemetry": {
    "trace_id": "tr_01HX",
    "request_id": "req_01HX",
    "latency_ms": 42,
    "cache_hit": false,
    "source_type": "cached",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Standard Telemetry Fields

Every response, including degraded and error responses, MUST include:

```json
{
  "trace_id": "string",
  "request_id": "string",
  "latency_ms": 0,
  "cache_hit": true,
  "source_type": "seeded",
  "retry_count": 0,
  "degraded": false,
  "external_api_called": false
}
```

No telemetry field may contain full prompts, full retrieved documents, secrets, API keys, or user private data beyond stable IDs.

### Default Cost Policy

Unless a tool overrides the values below:

- `cacheable`: `true`
- `max_retry_count`: `1`
- `external_api_allowed`: `false`
- `timeout_ms`: `1500`
- `retry_backoff_ms`: `200`
- Live external data is disabled by default.
- Retrying MUST only happen for transient infrastructure errors, not empty results or validation errors.
- Degraded responses MUST include `degraded: true`, a `degraded_reason`, and the best available cached or seeded data.

### Schema Strictness

All schemas in this document are closed contracts. Implementations MUST NOT add undocumented input, output, error, or telemetry fields without updating this file. Optional fields are documented in each tool section or shown with nullable/empty defaults in the JSON examples.

## Tool Contracts

## get_match_state

Returns current or cached match status, score, clock, and basic momentum inputs. Deterministic ranking or hotspot scoring does not belong in this tool.

### Input Schema

```json
{
  "match_id": "string",
  "include_timeline": false,
  "allow_external": false
}
```

Fields:

- `match_id`: required stable match ID.
- `include_timeline`: optional boolean, defaults to `false`.
- `allow_external`: optional boolean, defaults to `false`; live provider calls are only allowed when this is `true` and the environment permits external access.

### Output Schema

```json
{
  "ok": true,
  "tool": "get_match_state",
  "source_type": "cached",
  "data": {
    "match_id": "match_123",
    "home_team_id": "team_home",
    "away_team_id": "team_away",
    "status": "live",
    "minute": 67,
    "score": {
      "home": 2,
      "away": 1
    },
    "venue_id": "venue_456",
    "competition": "World Cup",
    "started_at": "2026-06-18T19:00:00Z",
    "last_updated_at": "2026-06-18T20:24:00Z",
    "timeline": [
      {
        "minute": 64,
        "event_type": "goal",
        "team_id": "team_home",
        "player_id": "player_9",
        "description": "Goal from open play."
      }
    ]
  },
  "telemetry": {
    "trace_id": "tr_01",
    "request_id": "req_01",
    "latency_ms": 35,
    "cache_hit": true,
    "source_type": "cached",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `MATCH_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`, `EXTERNAL_DISABLED`.

### Timeout Behavior

- `timeout_ms`: `1200`
- On timeout, return cached stale match state when available.

### Retry Behavior

- `max_retry_count`: `1`
- Retry only Supabase/local cache transient failures.
- Do not retry live provider calls unless `allow_external` is `true`.

### Degraded Response Behavior

If live or fresh cached state is unavailable, return the most recent cached state with:

```json
{
  "degraded_reason": "STALE_MATCH_STATE",
  "staleness_seconds": 420
}
```

### Cost and Cache Policy

- `cacheable`: `true`
- `cache_ttl_seconds`: `15` for live matches, `86400` for completed matches
- `external_api_allowed`: `false` by default
- Default source priority: `cached`, `seeded`, `external`

## get_team_profile

Returns team identity, roster highlights, tactical notes, and seeded/cached context for synthesis.

### Input Schema

```json
{
  "team_id": "string",
  "include_players": true,
  "include_tactics": true,
  "allow_external": false
}
```

### Output Schema

```json
{
  "ok": true,
  "tool": "get_team_profile",
  "source_type": "seeded",
  "data": {
    "team_id": "team_usa",
    "name": "United States",
    "country_code": "USA",
    "manager": "Example Manager",
    "style_summary": "High pressing with wide transition patterns.",
    "key_players": [
      {
        "player_id": "player_10",
        "name": "Example Player",
        "position": "AM",
        "insight": "Primary chance creator between the lines."
      }
    ],
    "tactical_notes": [
      "Often builds through the right half-space."
    ],
    "last_updated_at": "2026-05-01T00:00:00Z"
  },
  "telemetry": {
    "trace_id": "tr_02",
    "request_id": "req_02",
    "latency_ms": 28,
    "cache_hit": true,
    "source_type": "seeded",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `TEAM_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`, `EXTERNAL_DISABLED`.

### Timeout Behavior

- `timeout_ms`: `1000`
- Return minimal team identity if rich profile lookup times out.

### Retry Behavior

- `max_retry_count`: `1`
- Retry only cache/database transient failures.

### Degraded Response Behavior

Return identity-only data with empty arrays for unavailable optional sections and `degraded_reason: "PARTIAL_TEAM_PROFILE"`.

### Cost and Cache Policy

- `cacheable`: `true`
- `cache_ttl_seconds`: `604800`
- `external_api_allowed`: `false` by default
- Default source priority: `seeded`, `cached`, `external`

## get_city_profile

Returns city identity, travel context, neighborhood summaries, and static operational context.

### Input Schema

```json
{
  "city_id": "string",
  "locale": "en-US",
  "allow_external": false
}
```

### Output Schema

```json
{
  "ok": true,
  "tool": "get_city_profile",
  "source_type": "seeded",
  "data": {
    "city_id": "city_toronto",
    "name": "Toronto",
    "country_code": "CAN",
    "timezone": "America/Toronto",
    "summary": "Large multicultural host city with dense downtown transit coverage.",
    "neighborhoods": [
      {
        "neighborhood_id": "nb_king_west",
        "name": "King West",
        "summary": "Nightlife-heavy district near downtown hotels."
      }
    ],
    "transit_summary": "Subway, streetcar, commuter rail, and rideshare coverage.",
    "last_updated_at": "2026-05-01T00:00:00Z"
  },
  "telemetry": {
    "trace_id": "tr_03",
    "request_id": "req_03",
    "latency_ms": 18,
    "cache_hit": true,
    "source_type": "seeded",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `CITY_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`.

### Timeout Behavior

- `timeout_ms`: `1000`
- Return seeded city name/timezone if profile enrichment times out.

### Retry Behavior

- `max_retry_count`: `1`
- Retry only local/Supabase transient failures.

### Degraded Response Behavior

Return minimal city identity with `degraded_reason: "PARTIAL_CITY_PROFILE"`.

### Cost and Cache Policy

- `cacheable`: `true`
- `cache_ttl_seconds`: `2592000`
- `external_api_allowed`: `false`
- Default source priority: `seeded`, `cached`

## get_fan_hotspots

Returns backend-computed supporter hotspot candidates and evidence. This tool does not calculate hotspot scores in the AI layer.

### Input Schema

```json
{
  "city_id": "string",
  "match_id": "string",
  "team_id": "string",
  "limit": 10,
  "include_evidence": true,
  "allow_external": false
}
```

### Output Schema

```json
{
  "ok": true,
  "tool": "get_fan_hotspots",
  "source_type": "cached",
  "data": {
    "city_id": "city_toronto",
    "match_id": "match_123",
    "team_id": "team_usa",
    "hotspots": [
      {
        "hotspot_id": "hotspot_1",
        "venue_id": "venue_pub_1",
        "name": "Example Supporters Pub",
        "neighborhood": "King West",
        "confidence": "medium",
        "verified_signals": [
          "Partner venue listing"
        ],
        "inferred_signals": [
          "Near stadium transit corridor"
        ],
        "score": 0.78,
        "evidence_ids": [
          "doc_123"
        ]
      }
    ],
    "computed_at": "2026-06-18T16:00:00Z"
  },
  "telemetry": {
    "trace_id": "tr_04",
    "request_id": "req_04",
    "latency_ms": 44,
    "cache_hit": true,
    "source_type": "cached",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `HOTSPOTS_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`, `EXTERNAL_DISABLED`.

### Timeout Behavior

- `timeout_ms`: `1500`
- Return cached city-level hotspots when match/team-specific lookup times out.

### Retry Behavior

- `max_retry_count`: `1`
- Retry only transient cache/database failures.

### Degraded Response Behavior

Return city-level or seeded venue candidates with `degraded_reason: "NON_MATCH_SPECIFIC_HOTSPOTS"` and preserve verified vs inferred signal arrays.

### Cost and Cache Policy

- `cacheable`: `true`
- `cache_ttl_seconds`: `3600`
- `external_api_allowed`: `false` by default
- Default source priority: `cached`, `seeded`, `external`

## get_venues

Returns venue records for stadiums, pubs, restaurants, attractions, and creator-relevant locations.

### Input Schema

```json
{
  "city_id": "string",
  "venue_type": "pub",
  "neighborhood_id": "string",
  "limit": 20,
  "allow_external": false
}
```

Allowed `venue_type` values: `stadium`, `pub`, `restaurant`, `attraction`, `nightlife`, `hotel`, `transit`, `any`.

### Output Schema

```json
{
  "ok": true,
  "tool": "get_venues",
  "source_type": "cached",
  "data": {
    "city_id": "city_toronto",
    "venues": [
      {
        "venue_id": "venue_pub_1",
        "name": "Example Supporters Pub",
        "venue_type": "pub",
        "neighborhood_id": "nb_king_west",
        "address": "123 Example St",
        "geo": {
          "lat": 43.6426,
          "lng": -79.3871
        },
        "tags": [
          "supporters",
          "late-night"
        ],
        "source_type": "cached",
        "last_updated_at": "2026-05-15T00:00:00Z"
      }
    ]
  },
  "telemetry": {
    "trace_id": "tr_05",
    "request_id": "req_05",
    "latency_ms": 31,
    "cache_hit": true,
    "source_type": "cached",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `CITY_NOT_FOUND`, `VENUES_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`.

### Timeout Behavior

- `timeout_ms`: `1200`
- Return seeded venues when cached filtered lookup times out.

### Retry Behavior

- `max_retry_count`: `1`
- Retry only transient cache/database failures.

### Degraded Response Behavior

Return unfiltered city venues or seeded fallback venues with `degraded_reason: "FILTERED_VENUES_UNAVAILABLE"`.

### Cost and Cache Policy

- `cacheable`: `true`
- `cache_ttl_seconds`: `86400`
- `external_api_allowed`: `false` by default
- Default source priority: `cached`, `seeded`, `external`

## get_city_events

Returns cached or seeded city events relevant to matchday, nightlife, tourism, or creator content.

### Input Schema

```json
{
  "city_id": "string",
  "start_date": "2026-06-18",
  "end_date": "2026-06-20",
  "category": "nightlife",
  "limit": 20,
  "allow_external": false
}
```

Allowed `category` values: `matchday`, `nightlife`, `tourism`, `music`, `food`, `sports`, `any`.

### Output Schema

```json
{
  "ok": true,
  "tool": "get_city_events",
  "source_type": "cached",
  "data": {
    "city_id": "city_toronto",
    "events": [
      {
        "event_id": "event_1",
        "name": "Example Matchday Block Party",
        "category": "matchday",
        "starts_at": "2026-06-18T22:00:00-04:00",
        "ends_at": "2026-06-19T01:00:00-04:00",
        "venue_id": "venue_pub_1",
        "source_type": "cached",
        "confidence": "medium"
      }
    ]
  },
  "telemetry": {
    "trace_id": "tr_06",
    "request_id": "req_06",
    "latency_ms": 39,
    "cache_hit": true,
    "source_type": "cached",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `CITY_NOT_FOUND`, `EVENTS_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`, `EXTERNAL_DISABLED`.

### Timeout Behavior

- `timeout_ms`: `1500`
- Return seeded evergreen events or empty result with explanation on timeout.

### Retry Behavior

- `max_retry_count`: `1`
- Retry only transient cache/database failures.

### Degraded Response Behavior

Return seeded evergreen activities with `degraded_reason: "DATED_EVENTS_UNAVAILABLE"` and avoid claiming live event certainty.

### Cost and Cache Policy

- `cacheable`: `true`
- `cache_ttl_seconds`: `21600`
- `external_api_allowed`: `false` by default
- Default source priority: `cached`, `seeded`, `external`

## search_documents

Searches retrieved evidence documents for agent synthesis. This tool provides evidence snippets and metadata, not final reasoning.

### Input Schema

```json
{
  "query": "supporter pubs near stadium",
  "filters": {
    "city_id": "city_toronto",
    "match_id": "match_123",
    "team_id": "team_usa",
    "document_type": "venue_evidence"
  },
  "limit": 5,
  "include_snippets": true,
  "allow_external": false
}
```

Allowed `document_type` values: `match_context`, `team_profile`, `venue_evidence`, `city_guide`, `event_listing`, `creator_note`, `any`.

### Output Schema

```json
{
  "ok": true,
  "tool": "search_documents",
  "source_type": "cached",
  "data": {
    "results": [
      {
        "document_id": "doc_123",
        "document_type": "venue_evidence",
        "title": "Supporter Pub Listing",
        "snippet": "Partner listing identifies this venue as a supporters gathering location.",
        "source_type": "cached",
        "relevance_score": 0.84,
        "created_at": "2026-05-15T00:00:00Z"
      }
    ]
  },
  "telemetry": {
    "trace_id": "tr_07",
    "request_id": "req_07",
    "latency_ms": 52,
    "cache_hit": true,
    "source_type": "cached",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `SEARCH_UNAVAILABLE`, `DATA_UNAVAILABLE`, `TIMEOUT`.

### Timeout Behavior

- `timeout_ms`: `1800`
- Return partial results collected before timeout when possible.

### Retry Behavior

- `max_retry_count`: `1`
- Retry only transient vector/database failures.

### Degraded Response Behavior

Return lexical or metadata-only results with `degraded_reason: "VECTOR_SEARCH_UNAVAILABLE"` when vector search is unavailable.

### Cost and Cache Policy

- `cacheable`: `true`
- `cache_ttl_seconds`: `3600`
- `external_api_allowed`: `false`
- Default source priority: `cached`, `seeded`, `user_generated`

## generate_itinerary

Formats an itinerary from backend-computed candidates and sequencing. This tool must not calculate ordering from scratch.

### Input Schema

```json
{
  "city_id": "string",
  "match_id": "string",
  "traveler_profile": {
    "party_size": 2,
    "interests": [
      "supporter pubs",
      "nightlife"
    ],
    "budget": "medium",
    "accessibility_needs": []
  },
  "ordered_candidate_ids": [
    "venue_pub_1",
    "event_1"
  ],
  "start_date": "2026-06-18",
  "end_date": "2026-06-20",
  "allow_external": false
}
```

### Output Schema

```json
{
  "ok": true,
  "tool": "generate_itinerary",
  "source_type": "cached",
  "data": {
    "itinerary_id": "itin_123",
    "city_id": "city_toronto",
    "match_id": "match_123",
    "days": [
      {
        "date": "2026-06-18",
        "items": [
          {
            "start_time": "18:00",
            "end_time": "20:00",
            "item_type": "venue",
            "item_id": "venue_pub_1",
            "title": "Pre-match supporters pub",
            "explanation": "Selected from backend-ranked supporter hotspot candidates."
          }
        ]
      }
    ],
    "assumptions": [
      "Sequencing was supplied by backend preprocessing."
    ]
  },
  "telemetry": {
    "trace_id": "tr_08",
    "request_id": "req_08",
    "latency_ms": 66,
    "cache_hit": false,
    "source_type": "cached",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `MISSING_ORDERED_CANDIDATES`, `ITINERARY_GENERATION_FAILED`, `TIMEOUT`.

### Timeout Behavior

- `timeout_ms`: `2500`
- Return a minimal schedule skeleton when formatting exceeds timeout.

### Retry Behavior

- `max_retry_count`: `0`
- Do not retry generation by default to control token cost.

### Degraded Response Behavior

Return a compact itinerary skeleton with `degraded_reason: "ITINERARY_FORMATTING_TIMEOUT"` and preserve the supplied candidate order.

### Cost and Cache Policy

- `cacheable`: `true` when inputs are identical
- `cache_ttl_seconds`: `86400`
- `external_api_allowed`: `false`
- Default source priority: `cached`, `seeded`, `user_generated`

## get_route_context

Returns backend-computed route and transit context between known itinerary points. This tool does not optimize the itinerary order.

### Input Schema

```json
{
  "city_id": "string",
  "origin": {
    "type": "venue",
    "id": "venue_pub_1"
  },
  "destination": {
    "type": "venue",
    "id": "stadium_1"
  },
  "departure_time": "2026-06-18T17:30:00-04:00",
  "mode": "transit",
  "allow_external": false
}
```

Allowed `mode` values: `walk`, `transit`, `rideshare`, `drive`, `any`.

### Output Schema

```json
{
  "ok": true,
  "tool": "get_route_context",
  "source_type": "cached",
  "data": {
    "city_id": "city_toronto",
    "origin_id": "venue_pub_1",
    "destination_id": "stadium_1",
    "mode": "transit",
    "estimated_duration_minutes": 24,
    "distance_km": 3.2,
    "route_summary": "Streetcar and short walk to stadium district.",
    "confidence": "medium",
    "computed_at": "2026-06-18T12:00:00Z"
  },
  "telemetry": {
    "trace_id": "tr_09",
    "request_id": "req_09",
    "latency_ms": 46,
    "cache_hit": true,
    "source_type": "cached",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `ROUTE_NOT_FOUND`, `DATA_UNAVAILABLE`, `TIMEOUT`, `EXTERNAL_DISABLED`.

### Timeout Behavior

- `timeout_ms`: `1500`
- Return static city transit context if point-to-point route lookup times out.

### Retry Behavior

- `max_retry_count`: `1`
- Retry only transient cache/database failures.

### Degraded Response Behavior

Return approximate mode guidance with `degraded_reason: "POINT_TO_POINT_ROUTE_UNAVAILABLE"` and no precise duration claim unless cached.

### Cost and Cache Policy

- `cacheable`: `true`
- `cache_ttl_seconds`: `3600`
- `external_api_allowed`: `false` by default
- Default source priority: `cached`, `seeded`, `external`

## create_creator_script

Creates a short creator-facing script from supplied evidence and itinerary context. It may synthesize and explain, but must preserve evidence boundaries.

### Input Schema

```json
{
  "creator_id": "creator_123",
  "script_type": "short_video",
  "tone": "energetic",
  "target_seconds": 45,
  "context": {
    "city_id": "city_toronto",
    "match_id": "match_123",
    "team_id": "team_usa",
    "itinerary_id": "itin_123",
    "evidence_ids": [
      "doc_123"
    ]
  },
  "allow_external": false
}
```

Allowed `script_type` values: `short_video`, `match_preview`, `city_guide`, `hotspot_roundup`, `itinerary_walkthrough`.

### Output Schema

```json
{
  "ok": true,
  "tool": "create_creator_script",
  "source_type": "user_generated",
  "data": {
    "script_id": "script_123",
    "creator_id": "creator_123",
    "script_type": "short_video",
    "target_seconds": 45,
    "title": "Toronto Matchday Night Out",
    "segments": [
      {
        "label": "hook",
        "text": "Toronto matchday starts before kickoff if you know where supporters are gathering.",
        "evidence_ids": [
          "doc_123"
        ]
      }
    ],
    "evidence_disclaimer": "Verified venue signals are separated from inferred crowd activity.",
    "created_at": "2026-06-18T12:00:00Z"
  },
  "telemetry": {
    "trace_id": "tr_10",
    "request_id": "req_10",
    "latency_ms": 93,
    "cache_hit": false,
    "source_type": "user_generated",
    "retry_count": 0,
    "degraded": false,
    "external_api_called": false
  }
}
```

### Error Schema

Uses the standard error schema. Expected codes: `INVALID_INPUT`, `MISSING_EVIDENCE`, `SCRIPT_GENERATION_FAILED`, `TIMEOUT`.

### Timeout Behavior

- `timeout_ms`: `2500`
- Return a script outline when full script generation exceeds timeout.

### Retry Behavior

- `max_retry_count`: `0`
- Do not retry generation by default to control token cost.

### Degraded Response Behavior

Return a structured outline with `degraded_reason: "SCRIPT_GENERATION_TIMEOUT"` and include evidence IDs without unsupported claims.

### Cost and Cache Policy

- `cacheable`: `true` when inputs are identical
- `cache_ttl_seconds`: `86400`
- `external_api_allowed`: `false`
- Default source priority: `user_generated`, `cached`, `seeded`
