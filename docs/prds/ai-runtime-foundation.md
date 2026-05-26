# PRD: AI Runtime Foundation

## Problem Statement

The throughball-ai repo needs a minimal, local-first AI runtime foundation before agent orchestration, MCP tools, evals, and confidence systems can be implemented safely. Today the repo contains contracts and project guidance, but no Python application runtime, typed configuration, model routing module, telemetry helper, or health endpoint. This blocks follow-on AI tickets because there is no shared place to load Vertex AI configuration, enforce the Gemini Flash-only model policy, emit cost-aware structured telemetry, or verify that the service starts locally.

This matters now because the system is intended to demonstrate production AI orchestration discipline while staying low-cost. The foundation must make the cheap, deterministic path the default: local startup should not require live model calls, health checks should not spend money, and model selection should be constrained to Gemini Flash unless a later ticket deliberately changes that policy.

## Solution

Create a Python service foundation for throughball-ai with a small HTTP runtime, typed environment configuration, deterministic model routing, structured telemetry helpers, and placeholder module boundaries for orchestration, agents, MCP, evals, and Vertex/Google ADK integration.

The service should start locally, expose a health route, load Vertex AI-related configuration from environment variables, and provide a model router that always defaults to Gemini Flash. It should include the required dependencies for Google ADK, Vertex AI SDK, MCP SDK, OpenTelemetry, dotenv config, and structured logging, while avoiding live Vertex calls during startup or health checks.

The runtime should be ready for later tickets to add actual model calls and agent workflows, but this foundation should not perform recursive calls, automatic multi-agent loops, paid hosted telemetry, or external MCP tool calls.

## User Stories

1. As a developer, I want to start the AI service locally, so that I can verify the runtime foundation before building orchestration features.

2. As a developer, I want a health route, so that I can quickly confirm the service is running and configuration is loaded.

3. As a developer, I want health checks to avoid live Vertex AI calls, so that local startup does not require credentials or incur model cost.

4. As a developer, I want Vertex AI configuration loaded from environment variables, so that local, preview, and production settings can differ without code changes.

5. As a developer, I want typed configuration with dotenv support, so that missing or malformed runtime settings are easier to detect.

6. As a developer, I want the default model route to use Gemini Flash, so that the repo's low-cost AI policy is enforced by default.

7. As a developer, I want the escalation route to also use Gemini Flash for now, so that escalation behavior exists without introducing a more expensive model.

8. As a developer, I want max output tokens capped by configuration, so that accidental verbose completions are constrained.

9. As a developer, I want factual task temperature to default low, so that later agent outputs are more stable.

10. As a developer, I want the model router to return route metadata without making model calls, so that routing can be tested deterministically.

11. As a developer, I want every future model call to have a standard telemetry shape, so that cost and token usage can be tracked consistently.

12. As a developer, I want telemetry helpers to log `estimated_cost`, `prompt_tokens`, `completion_tokens`, and `total_tokens` when available, so that AI usage remains observable.

13. As a developer, I want telemetry helpers to tolerate unavailable provider usage metadata, so that logging does not fail when token counts are absent.

14. As a developer, I want structured JSON logs to stdout, so that local development and later log collection share the same event format.

15. As a developer, I want OpenTelemetry available without mandatory hosted exporters, so that tracing can be expanded later without adding paid infrastructure now.

16. As a developer, I want MCP foundation modules to exist without live external tools, so that later MCP work has a clear integration boundary.

17. As a developer, I want agent and orchestrator modules to exist without automatic loops, so that later agent work can build on stable package boundaries.

18. As a developer, I want eval modules to exist as lightweight placeholders, so that evaluation work has a home without adding eval loops in this ticket.

19. As a developer, I want tests for config, health, routing, and telemetry contracts, so that foundational behavior is protected as the runtime grows.

20. As an operator, I want health output to show configuration readiness without exposing secrets, so that debugging is useful but safe.

21. As an operator, I want telemetry events to avoid full prompts, completions, documents, secrets, and private user data, so that observability remains low-risk.

22. As a future agent implementer, I want a clear distinction between deterministic backend responsibilities and AI synthesis responsibilities, so that the runtime does not drift into model-based ranking, filtering, scoring, or itinerary sequencing.

## Implementation Decisions

- The implementation target is throughball-ai. Any `worldpulse-ai` references in the originating ticket are stale rename artifacts.
- The service will use a small FastAPI HTTP runtime with a `GET /health` route.
- The Python project will use package-style source layout under a `src` package namespace.
- The runtime entrypoint will expose an ASGI app that can be launched with uvicorn for local development.
- Configuration will be typed and loaded from environment variables with dotenv support.
- Supported configuration will include environment, service name, Google Cloud project, Google Cloud location, Vertex AI enabled state, Gemini Flash model identifier, max output token cap, and default factual temperature.
- Health checks will report service status, environment, default model, and whether Vertex AI configuration appears present, without exposing credentials or making live provider calls.
- Vertex AI initialization will be configuration-aware but will not perform model calls during application startup or health checks.
- The default model identifier will be environment-driven with a Gemini Flash fallback.
- Default and escalation routes will both resolve to Gemini Flash for this ticket.
- The model router will be deterministic and will return route metadata such as model id, max output tokens, temperature, and escalation state.
- This ticket will not implement real Gemini requests unless a later ticket explicitly introduces the model-call execution path.
- A cost estimator will exist as a lightweight, versioned helper. It may return zero when token data or pricing data is unavailable rather than pretending to know exact cost.
- Model-call telemetry helpers will emit contract-aligned structured events with token fields, estimated cost, latency, retry count, degraded mode, and route/model metadata where available.
- Structured JSON logging to stdout is the default observability mechanism.
- OpenTelemetry will be included as a dependency and may have a local helper or stub, but no remote exporter will be required.
- MCP modules will define local foundation boundaries and shared helpers only. Actual external MCP tool implementations are out of scope.
- Google ADK will be included as a dependency and may have an adapter or factory boundary, but full agent workflow execution is out of scope.
- Orchestrator and agent modules will be created as stable boundaries without recursive calls or automatic multi-agent loops.
- Eval modules will be created as stable boundaries without running eval loops automatically.
- The runtime must preserve the repo rule that AI explains, synthesizes, orchestrates, routes, and summarizes, while deterministic ranking, filtering, scoring, and itinerary ordering belong outside model prompts.

## Testing Decisions

- Tests should verify external behavior and contracts rather than internal implementation details.
- Config tests should cover default values, dotenv/env overrides, and Vertex readiness behavior without requiring real Google credentials.
- Health route tests should verify the service responds locally and does not expose secrets.
- Model router tests should verify the default route uses Gemini Flash, escalation still uses Gemini Flash, max output tokens are capped, and temperature defaults are low.
- Telemetry tests should verify emitted model-call event shape includes estimated cost and token fields, including behavior when provider usage metadata is absent.
- Logging tests should focus on structured event payloads rather than exact logger internals.
- No tests should make live Vertex AI, Gemini, MCP, or external network calls for this ticket.
- There is no existing Python test pattern in the repo, so this ticket should establish a minimal pytest pattern for future AI runtime work.

## Out of Scope

- Real Gemini model execution.
- Gemini Pro or expensive reasoning model support.
- Automatic model escalation to a higher-cost model.
- Automatic multi-agent loops.
- Recursive agent calls.
- Live external MCP tools.
- Backend ranking, filtering, hotspot scoring, or itinerary sequencing.
- Hosted observability platforms or mandatory remote telemetry exporters.
- Full prompt, completion, retrieved document, secret, or private data logging.
- Production deployment infrastructure.
- Authentication and authorization.
- Database schema or persistence changes.

## Further Notes

- The repo is intentionally low-cost and orchestration-first. This foundation should make low-cost behavior the easiest path.
- The observability contract in the repo is the source of truth for telemetry field names and event taxonomy.
- The MCP contract in the repo is the source of truth for later tool response telemetry and degraded behavior.
- The default local development experience should work from a copied `.env` file and should not require paid services just to start the application.
- Pricing and model identifiers can change over time; model names and cost behavior should be configuration-driven where practical.
- Later tickets should add the actual model execution adapter, agent-specific prompts, MCP tool implementations, eval cases, retries, and confidence systems on top of this foundation.
