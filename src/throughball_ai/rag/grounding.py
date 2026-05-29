import re


class GroundingEvaluator:
    """Heuristic groundedness check — no LLM calls.

    Two failure conditions:
      1. retrieval_confidence == "none" → no evidence was found.
      2. The answer contains no [N] citation marker that maps to a valid chunk index.
    """

    def evaluate(
        self,
        *,
        answer: str,
        retrieval_confidence: str,
        chunk_count: int,
    ) -> dict:
        if retrieval_confidence == "none":
            return {
                "grounded": False,
                "groundedness_reason": (
                    "Retrieval confidence is 'none' — no supporting evidence was retrieved."
                ),
            }

        cited_ids = _extract_citation_ids(answer)
        valid_ids = {n for n in cited_ids if 1 <= n <= chunk_count}

        if not valid_ids:
            return {
                "grounded": False,
                "groundedness_reason": (
                    "Answer contains no valid citation markers ([N]) referencing retrieved chunks."
                ),
            }

        return {
            "grounded": True,
            "groundedness_reason": (
                f"Answer cites {len(valid_ids)} retrieved source(s) with valid [N] markers."
            ),
        }


def _extract_citation_ids(text: str) -> list[int]:
    return [int(m) for m in re.findall(r"\[(\d+)\]", text)]
