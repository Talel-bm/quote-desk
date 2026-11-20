# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Early scaffold: `src/quote_desk/__init__.py` only defines a placeholder `main()`, there are no tests yet, and `README.md` is empty. Update this file as real modules are added.

## Tooling

Python 3.12, managed with **uv** (`uv_build` backend, `src/` layout, lockfile in `uv.lock`).

```sh
uv sync                      # install deps + dev group (pytest, ruff)
uv run quote-desk            # run the CLI entry point (quote_desk:main)
uv run pytest                # run all tests
uv run pytest path/to/test_file.py::test_name   # run a single test
uv run ruff check .          # lint
uv run ruff format .         # format
uv add <pkg> / uv add --dev <pkg>   # add dependencies (keeps uv.lock in sync)
```

## Environment & data

- Secrets/config come from a `.env` file at the repo root (git-ignored; `python-dotenv` is a dependency). Don't commit it.
- `data/generated/` is git-ignored — treat it as an output location for generated data, not source.

## Declared stack

Dependencies in `pyproject.toml` indicate the intended building blocks, though none are wired up yet:
- API/UI: FastAPI + uvicorn, Streamlit
- LLM clients: `google-genai` (Gemini) and `ollama` (local models)
- ML: LightGBM, scikit-learn, SHAP (explainability), pandas/numpy
- Inputs/fixtures: `pypdf` (PDF parsing), `faker` (synthetic data), `httpx`

## Goal and Rules
- "I'm building a portfolio demo I must be able to explain line by line.
Work in small steps. Before writing code, show a short plan. After
writing code, explain what each new function does in plain language."
- "Python 3.12 via uv. Add dependencies only with `uv add`, and ask first."
- "Keep it simple: no frameworks beyond the stack in SPEC.md. No LangChain."
- "Every LLM output is validated with Pydantic and retried on failure."
- "All data is synthetic. Never use real company names except in the README's
         closing context section."
- "Write a pytest test for each module."
- "Commit after each finished step with a clear message."