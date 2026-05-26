from fastapi import FastAPI

from throughball_ai.config import get_settings

app = FastAPI(title="throughball-ai")


@app.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.service_name,
        "environment": settings.environment,
        "model_default": settings.gemini_flash_model,
        "vertex_ai_configured": settings.vertex_ai_configured,
    }
