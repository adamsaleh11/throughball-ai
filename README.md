# throughball-ai

Throughball AI orchestration repo for local-first demo development.

## Scope

- orchestration
- MCP
- Gemini Flash integration
- AI reasoning synthesis
- evals
- retries
- confidence systems
- telemetry

## Development Principles

- Keep local development as the default.
- Use Gemini Flash only for demo AI calls.
- Do not add paid SaaS tools by default.
- Do not add hosted observability tools by default.
- Do not add always-on infrastructure.
- Deploy to cloud only when needed for the demo.

## Getting Started

```sh
cp .env.example .env
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m uvicorn throughball_ai.main:app --reload --host 127.0.0.1 --port 8001
```

Health check:

```sh
curl http://127.0.0.1:8001/health
```

Run tests:

```sh
python -m pytest
```
