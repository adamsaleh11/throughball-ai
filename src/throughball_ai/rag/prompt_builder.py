from throughball_ai.retrieval.documents import MAX_CHUNK_CHARS


def build_grounded_context(
    *,
    chunks: list[str],
    source_paths: list[str],
    titles: list[str],
    top_k: int = 5,
) -> str:
    """Render retrieved chunks as numbered XML source blocks for LLM injection.

    Total output is capped at top_k * MAX_CHUNK_CHARS characters.
    Blocks that would push past the cap are dropped entirely — never truncated.
    """
    if not chunks:
        return ""

    cap = top_k * MAX_CHUNK_CHARS
    parts: list[str] = []
    total = 0

    for i, (chunk, path) in enumerate(zip(chunks, source_paths), start=1):
        block = f'<source id="{i}" path="{path}">\n{chunk}\n</source>'
        if total + len(block) > cap:
            break
        parts.append(block)
        total += len(block)

    return "\n\n".join(parts)
