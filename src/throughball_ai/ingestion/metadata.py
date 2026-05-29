from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DocumentMetadata:
    source_path: str
    category: str
    title: str
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def city_id(self) -> str | None:
        return _metadata_id("city", self.fields.get("city"))

    @property
    def team_id(self) -> str | None:
        return _metadata_id("team", self.fields.get("team"))

    @property
    def source_type(self) -> str:
        value = self.fields.get("source_type", "").strip()
        return value if value and value.lower() != "null" else "seeded"


def extract_metadata(path: Path, corpus_root: Path, content: str) -> DocumentMetadata:
    relative_path = path.relative_to(corpus_root).as_posix()
    fields = _parse_metadata_block(content)
    title = _extract_title(content) or _title_from_filename(path)
    category = path.parent.name
    return DocumentMetadata(
        source_path=relative_path,
        category=category,
        title=title,
        fields=fields,
    )


def _parse_metadata_block(content: str) -> dict[str, str]:
    lines = content.splitlines()
    fields: dict[str, str] = {}
    in_metadata = False

    for line in lines:
        stripped = line.strip()
        if stripped == "## Metadata":
            in_metadata = True
            continue
        if in_metadata and stripped.startswith("## "):
            break
        if not in_metadata or not stripped or stripped.startswith("-"):
            continue
        key, separator, value = stripped.partition(":")
        if separator:
            fields[key.strip()] = value.strip()

    return fields


def _extract_title(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def _title_from_filename(path: Path) -> str:
    return path.stem.replace("-", " ").title()


def _metadata_id(prefix: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized or normalized == "null":
        return None
    slug = "-".join(normalized.replace("_", " ").split())
    return f"{prefix}_{slug.replace('-', '_')}"
