from dataclasses import dataclass
from typing import Sequence


ONLINE_EMBEDDING_PRICE_PER_1K_CHARS = 0.000025


@dataclass(frozen=True)
class EmbeddingCostEstimate:
    embedding_model: str
    chunks_to_embed: int
    billable_characters: int
    price_per_1k_chars: float
    estimated_cost_usd: float


def estimate_embedding_cost(
    chunk_texts: list[str],
    embedding_model: str,
    price_per_1k_chars: float = ONLINE_EMBEDDING_PRICE_PER_1K_CHARS,
) -> EmbeddingCostEstimate:
    billable_characters = sum(len(text) for text in chunk_texts)
    estimated_cost = (billable_characters / 1000) * price_per_1k_chars
    return EmbeddingCostEstimate(
        embedding_model=embedding_model,
        chunks_to_embed=len(chunk_texts),
        billable_characters=billable_characters,
        price_per_1k_chars=price_per_1k_chars,
        estimated_cost_usd=round(estimated_cost, 8),
    )


class VertexTextEmbeddingClient:
    def __init__(
        self,
        project: str,
        location: str,
        model_name: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ):
        self.project = project
        self.location = location
        self.model_name = model_name
        self.task_type = task_type
        self._model = None

    BATCH_SIZE = 20

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        from vertexai.language_models import TextEmbeddingInput
        results: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            inputs = [TextEmbeddingInput(text, self.task_type) for text in batch]
            embeddings = model.get_embeddings(inputs)
            results.extend(_values_from_embedding(e) for e in embeddings)
        return results

    def _get_model(self):
        if self._model is None:
            import vertexai
            from vertexai.language_models import TextEmbeddingModel

            vertexai.init(project=self.project, location=self.location)
            self._model = TextEmbeddingModel.from_pretrained(self.model_name)
        return self._model


def _values_from_embedding(embedding) -> list[float]:
    values: Sequence[float] = getattr(embedding, "values", embedding)
    return [float(value) for value in values]
