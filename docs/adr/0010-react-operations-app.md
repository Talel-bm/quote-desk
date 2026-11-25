# 10. A React operations app instead of Streamlit

Status: Accepted (2026-11-24)

## Context
The demo needs pages Streamlit handles poorly:
- an approval inbox with keyboard triage;
- live agent runs over SSE;
- a 10-day replay with a time scrubber;
- a connect-a-source wizard.

The author already built and deployed FastAPI + SSE + React (Vite, TypeScript, Tailwind,
shadcn/ui, Recharts, React Flow) in a previous project, including the Docker build, the
Space deploy scripts and freshness tests.

## Decision
Reuse that stack. One uvicorn process serves `/api/*` and the built app. TypeScript types
are generated from the OpenAPI schema, and CI fails on drift. Every number on a page comes
from the API or from a generated JSON file covered by a freshness test. The owner sees
ASCII options for each page and looks at the page before it is committed. Streamlit is
removed.

## Consequences
Node is needed at build time only. More frontend code, most of it ported rather than new.
