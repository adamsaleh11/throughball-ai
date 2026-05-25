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
```

Add implementation-specific setup commands as the AI stack is introduced.
