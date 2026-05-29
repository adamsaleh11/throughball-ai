# Vancouver Fan Hotspots

## Metadata

city: Vancouver
country: Canada
team: null
category: fan-hotspots
source_name: FIFA host and stadium information + official venue, tourism, transit, and public-safety sources
source_url: https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/canada/vancouver
source_urls:
- https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/canada/vancouver
- https://www.fifa.com/en/articles/stadium-information-details
- https://www.bcplace.com/
- https://www.destinationvancouver.com/
- https://www.translink.ca/
last_updated: 2026-05-27
confidence: medium
tags: vancouver,fan-hotspots,world-cup-2026,football,travel

## Verified Signals

Curated supporter-relevant districts for Vancouver are Yaletown, Gastown, False Creek, Granville Street, Coal Harbour. These are not claims that fans are currently gathered there; they are stable nightlife, visitor, stadium, or transit-adjacent anchors drawn from official tourism geography and local event planning context. Use them as retrieval anchors for watch-party, meetup, and fan-zone explanation.

## Inferred Signals

For high-demand fixtures, supporters are likely to cluster first around food, bars, hotel corridors, and transit-friendly neighborhoods before moving toward BC Place. In Vancouver, that means the AI can discuss Yaletown, Gastown, False Creek, Granville Street, Coal Harbour as likely social geography while clearly separating inferred crowd behavior from verified events. Team-specific gathering claims require current event listings, club announcements, or official fan-zone information.

## Retrieval Notes

Use for supporter gathering explanations, watch-location caveats, verified-versus-inferred signal handling, and confidence downgrades. Preserve backend hotspot order; do not calculate hotspot scores, filter venues, or create deterministic rankings in the AI layer.

## Source and Confidence Notes

Official or stable sources used for grounding include FIFA host/stadium pages, https://www.bcplace.com/, https://www.destinationvancouver.com/, and https://www.translink.ca/. District and visitor-area grounding comes from official tourism and venue context. Fan density, team-specific turnout, and live activity are inferred unless supported by current verified event sources.
