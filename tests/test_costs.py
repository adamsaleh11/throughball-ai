"""Tests for the cost estimator."""
import pytest
from throughball_ai.telemetry.costs import estimate_model_cost, ESTIMATOR_VERSION


def test_known_model_returns_nonzero_cost():
    cost, version = estimate_model_cost(1000, 500, "gemini-2.0-flash-001")
    assert cost > 0
    assert version == ESTIMATOR_VERSION


def test_cost_scales_with_token_count():
    small, _ = estimate_model_cost(100, 50, "gemini-2.0-flash-001")
    large, _ = estimate_model_cost(10000, 5000, "gemini-2.0-flash-001")
    assert large > small


def test_unknown_model_returns_zero_cost_with_unknown_version():
    cost, version = estimate_model_cost(1000, 500, "some-unknown-model")
    assert cost == 0.0
    assert version == "unknown-model-v1"


def test_zero_tokens_returns_zero_cost():
    cost, _ = estimate_model_cost(0, 0, "gemini-2.0-flash-001")
    assert cost == 0.0


def test_prompt_tokens_cost_less_than_completion_tokens():
    """Input tokens are cheaper than output for Gemini Flash."""
    input_only, _ = estimate_model_cost(1000, 0, "gemini-2.0-flash-001")
    output_only, _ = estimate_model_cost(0, 1000, "gemini-2.0-flash-001")
    assert output_only > input_only


def test_all_listed_models_have_valid_pricing():
    from throughball_ai.telemetry.costs import _COST_PER_1K_TOKENS
    for model, (input_rate, output_rate) in _COST_PER_1K_TOKENS.items():
        assert input_rate > 0, f"{model} input rate must be > 0"
        assert output_rate > 0, f"{model} output rate must be > 0"
        assert output_rate >= input_rate, f"{model} output should cost >= input"
