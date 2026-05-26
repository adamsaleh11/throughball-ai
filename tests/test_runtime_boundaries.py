import importlib


def test_runtime_foundation_boundaries_are_importable():
    for module_name in [
        "throughball_ai.agents",
        "throughball_ai.orchestrator",
        "throughball_ai.mcp",
        "throughball_ai.evals",
        "throughball_ai.telemetry",
        "throughball_ai.model_router",
    ]:
        assert importlib.import_module(module_name)
