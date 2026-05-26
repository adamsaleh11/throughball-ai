from throughball_ai.config import Settings
from throughball_ai.model_router import ModelRouter


def test_default_and_escalation_routes_use_gemini_flash():
    settings = Settings(
        GEMINI_FLASH_MODEL="gemini-2.0-flash-001",
        MAX_OUTPUT_TOKENS=384,
        DEFAULT_TEMPERATURE=0.1,
    )
    router = ModelRouter(settings)

    default_route = router.route("match_analyst")
    escalation_route = router.route("match_analyst", escalate=True)

    assert default_route.model == "gemini-2.0-flash-001"
    assert escalation_route.model == "gemini-2.0-flash-001"
    assert default_route.max_output_tokens == 384
    assert default_route.temperature == 0.1
    assert default_route.escalated is False
    assert escalation_route.escalated is True
