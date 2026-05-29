import re


def extract_citations(
    *,
    answer: str,
    source_paths: list[str],
    titles: list[str],
) -> list[dict]:
    """Extract inline [N] citation markers from an answer and map them to sources.

    - 1-indexed; out-of-range markers are silently dropped.
    - Duplicate markers produce a single citation entry.
    - Returns list ordered by first appearance of each unique N.
    """
    if not answer:
        return []

    seen: set[int] = set()
    citations: list[dict] = []

    for raw in re.findall(r"\[(\d+)\]", answer):
        n = int(raw)
        if n in seen:
            continue
        seen.add(n)
        idx = n - 1  # convert to 0-based
        if idx < 0 or idx >= len(source_paths):
            continue
        citations.append(
            {
                "id": n,
                "source_path": source_paths[idx],
                "title": titles[idx] if idx < len(titles) else "",
            }
        )

    return citations
