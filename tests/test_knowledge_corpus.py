from pathlib import Path


CORPUS_ROOT = Path("knowledge/seed-documents")

SUPPORTED_CITIES = {
    "atlanta",
    "boston",
    "dallas",
    "guadalajara",
    "houston",
    "kansas-city",
    "los-angeles",
    "mexico-city",
    "miami",
    "monterrey",
    "new-york-new-jersey",
    "philadelphia",
    "san-francisco-bay-area",
    "seattle",
    "toronto",
    "vancouver",
}

REQUIRED_CATEGORIES = {
    "cities",
    "venues",
    "fan-hotspots",
    "transportation",
    "match-previews",
    "tourism",
    "safety",
}

CATEGORY_SUFFIXES = {
    "cities": "city-overview",
    "venues": "stadium-guide",
    "fan-hotspots": "fan-hotspots",
    "transportation": "transportation",
    "match-previews": "match-preview",
    "tourism": "tourism",
    "safety": "safety",
}

CATEGORY_REQUIRED_PHRASES = {
    "cities": ("## City Snapshot", "## Retrieval Notes"),
    "venues": ("## Venue Context", "## Retrieval Notes"),
    "fan-hotspots": ("## Verified Signals", "## Inferred Signals"),
    "transportation": ("## Matchday Transportation", "## Retrieval Notes"),
    "match-previews": (
        "## Matchday Context",
        "## Likely Arrival and Departure Pattern",
        "## Source and Confidence Notes",
    ),
    "tourism": ("## Visitor Context", "## Retrieval Notes"),
    "safety": ("## Safety Context", "## Retrieval Notes"),
}

FORBIDDEN_ARTIFACT_SUFFIXES = {
    ".db",
    ".faiss",
    ".jsonl",
    ".npy",
    ".parquet",
    ".sqlite",
}

FORBIDDEN_ARTIFACT_NAME_PARTS = {
    "chunk",
    "embedding",
    "vector",
}


def test_seed_corpus_has_required_category_document_for_every_city():
    assert CORPUS_ROOT.exists()

    missing_categories = [
        category
        for category in sorted(REQUIRED_CATEGORIES)
        if not (CORPUS_ROOT / category).is_dir()
    ]
    assert missing_categories == []

    missing_documents = []
    for category in sorted(REQUIRED_CATEGORIES):
        suffix = CATEGORY_SUFFIXES[category]
        for city in sorted(SUPPORTED_CITIES):
            document = CORPUS_ROOT / category / f"{city}-{suffix}.md"
            if not document.is_file():
                missing_documents.append(str(document))

    assert missing_documents == []


def test_seed_corpus_documents_have_category_specific_retrieval_sections():
    missing_phrases = []

    for category in sorted(REQUIRED_CATEGORIES):
        suffix = CATEGORY_SUFFIXES[category]
        required_phrases = CATEGORY_REQUIRED_PHRASES[category]
        for city in sorted(SUPPORTED_CITIES):
            document = CORPUS_ROOT / category / f"{city}-{suffix}.md"
            content = document.read_text()
            for phrase in required_phrases:
                if phrase not in content:
                    missing_phrases.append(f"{document}: {phrase}")

    assert missing_phrases == []


def test_seed_corpus_documents_include_source_confidence_notes_and_stay_small():
    invalid_documents = []

    for document in sorted(CORPUS_ROOT.glob("*/*.md")):
        content = document.read_text()
        word_count = len(content.split())
        has_source_notes = "## Source and Confidence Notes" in content
        has_confidence_metadata = "confidence:" in content
        source_url_count = content.count("https://")
        if (
            not has_source_notes
            or not has_confidence_metadata
            or source_url_count < 3
            or word_count > 700
        ):
            invalid_documents.append(
                {
                    "path": str(document),
                    "has_source_notes": has_source_notes,
                    "has_confidence_metadata": has_confidence_metadata,
                    "source_url_count": source_url_count,
                    "word_count": word_count,
                }
            )

    assert invalid_documents == []


def test_seed_corpus_contains_source_markdown_only():
    forbidden_artifacts = []

    for path in CORPUS_ROOT.rglob("*"):
        if not path.is_file():
            continue

        lower_name = path.name.lower()
        has_forbidden_suffix = path.suffix.lower() in FORBIDDEN_ARTIFACT_SUFFIXES
        has_forbidden_name = any(part in lower_name for part in FORBIDDEN_ARTIFACT_NAME_PARTS)
        if path.suffix.lower() != ".md" or has_forbidden_suffix or has_forbidden_name:
            forbidden_artifacts.append(str(path))

    assert forbidden_artifacts == []
