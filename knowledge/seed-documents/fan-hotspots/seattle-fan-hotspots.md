# Seattle Fan Hotspots

## Metadata

city: Seattle
country: United States
team: null
category: fan-hotspots
source_name: FIFA host and stadium information + official venue, tourism, transit, and public-safety sources
source_url: https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/usa/seattle
source_urls:
- https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/usa/seattle
- https://www.fifa.com/en/articles/stadium-information-details
- https://www.lumenfield.com/
- https://visitseattle.org/
- https://www.soundtransit.org/
last_updated: 2026-05-27
confidence: medium
tags: seattle,fan-hotspots,world-cup-2026,football,travel

## Verified Signals

Curated supporter-relevant districts for Seattle are Pioneer Square, International District, Capitol Hill, Waterfront, Belltown. These are not claims that fans are currently gathered there; they are stable nightlife, visitor, stadium, or transit-adjacent anchors drawn from official tourism geography and local event planning context. Use them as retrieval anchors for watch-party, meetup, and fan-zone explanation.

## Inferred Signals

For high-demand fixtures, supporters are likely to cluster first around food, bars, hotel corridors, and transit-friendly neighborhoods before moving toward Lumen Field. In Seattle, that means the AI can discuss Pioneer Square, International District, Capitol Hill, Waterfront, Belltown as likely social geography while clearly separating inferred crowd behavior from verified events. Team-specific gathering claims require current event listings, club announcements, or official fan-zone information.

## Retrieval Notes

Use for supporter gathering explanations, watch-location caveats, verified-versus-inferred signal handling, and confidence downgrades. Preserve backend hotspot order; do not calculate hotspot scores, filter venues, or create deterministic rankings in the AI layer.

## Source and Confidence Notes

Official or stable sources used for grounding include FIFA host/stadium pages, https://www.lumenfield.com/, https://visitseattle.org/, and https://www.soundtransit.org/. District and visitor-area grounding comes from official tourism and venue context. Fan density, team-specific turnout, and live activity are inferred unless supported by current verified event sources.
