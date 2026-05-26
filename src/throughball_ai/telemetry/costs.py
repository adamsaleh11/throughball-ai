ESTIMATOR_VERSION = "static-zero-v1"


def estimate_model_cost(prompt_tokens: int, completion_tokens: int, model: str) -> tuple[float, str]:
    return 0.0, ESTIMATOR_VERSION
