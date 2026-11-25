# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Steps 0 (scaffold), 1 (generate) and 2 (foundation v1) are done. **`SPEC.md` v3 is the source of truth**: a two-plant group (North + acquired Québec), five families, a day-by-day world simulator with a sealed answer key, and build Steps 3-10 (one per day, 2026-11-25 to 2026-12-01; interview 2026-12-02). Design: `docs/architecture.md` (layers, dependency rules, stores, runtime, testing, threat model) and ADRs 0001-0016 in `docs/adr/`. Target packages (`core/ connectors/ products/ storage/ services/ evals/`, `web/`) are added as steps need them. `README.md` is still empty. Update this file as real modules are added.

## How each step is run (owner-approved; adapted from the owner's CoverageCheck project)

1. Read SPEC.md's section for the step. Survey the REAL data first with small scratch scripts, so the plan rests on evidence.
2. Show a short plan with the decisions that need the owner (recommend one option); wait for approval.
3. Code in small pure functions with docstrings that say why. Review outputs on real data by hand.
4. Tests: unit tests per rule; real-data tests; hand-checked cases as EXACT sets; a "never again" test for every bug found; then a mutation check (break each rule in memory via a scratch script, restore in `finally`, confirm some test fails; add a test for any survivor).
5. **One** independent audit agent per step: read-only, scratch outside the repo, briefed with the owner's decisions so it does not re-argue them. Verify every audit claim on real data before acting; show the owner a fix / record-for-later / reject table.
6. Update the step's status in SPEC.md (decisions, measured numbers, known limits), explain each new function in plain language, commit.

Evidence rules (ADR 0016): pass criteria go in `evals/preregistration.yaml` BEFORE a measured run and are applied as written; tune on dev sets only; the sealed world and intake held-out set are opened once after the freeze tag; every reported number is a `Metric` with CI, n and a Measured / Derived / Projected label; UI and README numbers come only from generated files with freshness tests. UI pages: show ASCII options first; the owner looks at each page before commit.

Private, git-ignored: `SPEC.private.md` (original v1 spec), `research.private/` (seven research reports + `00_mapping.md`). Never commit or quote them in tracked files.

## Architecture notes

- `src/quote_desk/config.py` is the single source of paths, `SEED`, and LLM settings (`LLM_PROVIDER`, Gemini/Ollama model names, read from `.env`; see `.env.example`). Don't rebuild paths or read env vars elsewhere.
- Two SQLite databases in `DATA_DIR` (`data/generated/`, overridable with `QUOTEDESK_DATA_DIR`): `erp.sqlite` is the synthetic ERP, rebuilt by `generate/` and treated as read-only after Foundation; `app.sqlite` holds app state (approval inbox, feedback, quotes) so regenerating the ERP never wipes it.
- Tests use the `tmp_data_dir` fixture in `tests/conftest.py` to redirect `DATA_DIR` to a temp folder.
- CLI subcommands live in `src/quote_desk/__init__.py` (argparse, lazy imports per command). Add new steps there (e.g. `clean`, `train`).

### Generate (`generate/`)
- Metal prices: copper/aluminum are **real** World Bank Pink Sheet data in the committed `data/raw/commodity_prices_worldbank.csv` (refresh with `quote-desk fetch-commodities`; provenance in `data/raw/README.md`). Electrical steel is **synthetic**, derived from real iron ore. History window is 2023-11 to 2026-10. Use `commodity.prices_on()` for any price lookup.
- `cost_model.py` holds the hidden "true cost" rules: planned cost (materials ∝ kVA^0.75, learning curve, wage inflation) plus hidden drivers the ERP never records (supplier spread, per-customer extra work, monthly shop load, noisier rare options, rework, rare major overruns). It is generator-only: never write its formulas into the ERP or import it from `forge/`, since the model must learn cost from job history.
- `synth_erp.build_erp(seed, n_jobs, messy=True)` builds clean tables, then `add_mess()` applies the deliberate mess (legacy duplicate part numbers, `quote`/`cancelled` rows in `jobs`, kg/lb mix in `boms`, ×10 unit-cost typos, ~3% blanks) using a separate RNG, so `messy=False` gives the identical clean data underneath.
- Generator eval `quote-desk check-generator`: out-of-the-box LightGBM on clean won jobs should land at ~10-20% MAPE (currently ~10-13% across seeds), with a formula oracle (exact plan, no hidden factors) as reference. Re-run it after any change to `cost_model.py` or job generation.
- Copper rises ~77% over the window, mostly in year 3, but the measured year-3 penalty for LightGBM is small (<1 MAPE point); still worth a material-cost-at-quote-date feature in Forge.

### Foundation (`foundation/`)
- **Generic engine + per-source contract.** `clean.py`, `profile.py`, `load.py`, `quality_report.py` contain no domain knowledge; all business meaning lives in `foundation/contracts/<source>.py` (keys, foreign keys, types, units, identity columns for duplicate merging, dataset filters, outlier comparison groups). A new source needs a new contract, not engine changes. `field_service_demo.py` + `data/samples/field_service/` prove this.
- **Must not exploit generator internals** (e.g. the `L4xxxx` prefix or exact ×10 factors). Contracts state only what a customer could say. The clean `messy=False` tables are used only in `tests/test_foundation_eval.py` to score cleaning (all typos caught, real overruns not sent to review).
- Agreed policies: outliers are **flagged, not removed** (`is_outlier`, `outlier_z`, `outlier_group`); only extreme cases (≥5× typical) and orphan references go to `review_queue`; everything else is automatic and logged in `audit`; excluded rows go to `quarantine` with a reason and the raw row; **missing values are left for Forge**; output is identical on rerun.
- Outputs in `data/generated/foundation.sqlite`: cleaned tables (same names), `cost_history` (what Forge trains on: won jobs + config + customer + outlier flags), `crosswalk`, `audit`, `quarantine`, `review_queue`. Forge should read from here, not from `erp.sqlite`, and map part numbers via the cleaned tables.
- Report (`quality_report.md`): plain-language summary + safeguards table first, technical detail after.
- New data flow (`foundation/cli.py`): profile → `draft_contract.py` guesses keys, types (tolerating ~5% bad values), and links (≥70% of values found), leaving TODOs for business rules → `load_contract_file()` executes a contract `.py` file (only load reviewed files). Outputs go to `data/generated/<source name>/`. On the ERP the draft recovers all hand-written keys and links.

## Git workflow

Repo is public (github.com/Talel-bm/quote-desk). One branch per SPEC step (`step-N-<name>`), small commits, then `git merge --no-ff` into `main` and push. Never squash-merge (keeps daily commits on the contribution graph) and never force-push. `SPEC.private.md` is git-ignored; don't name the target company in tracked files.

## Tooling

Python 3.12, managed with **uv** (`uv_build` backend, `src/` layout, lockfile in `uv.lock`).

```sh
uv sync                      # install deps + dev group (pytest, ruff)
uv run quote-desk generate   # build data/generated/erp.sqlite (--seed, --jobs)
uv run quote-desk check-generator     # eval: LightGBM MAPE on the clean synthetic data
uv run quote-desk clean               # Foundation: foundation.sqlite + quality_report.md
uv run quote-desk clean --demo        # same engine on the unrelated field-service sample
uv run quote-desk profile --source PATH          # any new data: CSV folder, .csv or SQLite
uv run quote-desk draft-contract --source PATH   # guessed contract (keys/types/links) to review
uv run quote-desk clean --source PATH [--contract FILE]  # no --contract = auto draft + clean
uv run quote-desk fetch-commodities   # one-time refresh of real metal prices (needs internet)
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

Dependencies in `pyproject.toml` indicate the intended building blocks (full target list in SPEC.md section 8; new ones are approved by the owner and added with `uv add` when a step needs them):
- API/UI: FastAPI + uvicorn (native SSE) serving a React app in `web/` (Vite, TypeScript, Tailwind, shadcn/ui, Recharts). Streamlit is being removed (ADR 0010).
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