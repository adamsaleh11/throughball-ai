ESTIMATOR_VERSION = "per-model-v1"

_COST_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash-001": (0.000075, 0.0003),
    "gemini-2.0-flash": (0.000075, 0.0003),
    "gemini-1.5-flash": (0.000075, 0.0003),
    "gemini-1.5-flash-8b": (0.0000375, 0.00015),
    "gemini-1.5-pro": (0.00125, 0.005),
    "gemini-2.0-pro": (0.00125, 0.005),
}


def estimate_model_cost(prompt_tokens: int, completion_tokens: int, model: str) -> tuple[float, str]:
    costs = _COST_PER_1K_TOKENS.get(model)
    if costs is None:
        return 0.0, "unknown-model-v1"
    input_cost = (prompt_tokens / 1000) * costs[0]
    output_cost = (completion_tokens / 1000) * costs[1]
    return round(input_cost + output_cost, 8), ESTIMATOR_VERSION
