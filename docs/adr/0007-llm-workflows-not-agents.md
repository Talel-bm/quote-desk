# 7. LLM use: fixed workflows, validated output, no frameworks

Status: Accepted (2026-11-24)

## Context
The quote process is well defined. Autonomous tool-using agents add unpredictability
where none is needed; frameworks add code nobody on the project can explain.

## Decision
Fixed steps with gates (a prompt chain plus routing). The LLM extracts typed data
only. Every output is validated with Pydantic and re-asked up to 2 times with the
validation error. Providers sit behind one `LLMClient` protocol: Gemini, Ollama, and
a scripted Fake used by tests and by the keyless public demo. No LangChain or agent
frameworks. Field confidence comes from deterministic checks, not model self-reports.

## Consequences
Behavior is testable and reproducible; the public demo never depends on a key.
