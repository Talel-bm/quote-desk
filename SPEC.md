Project: QuoteDesk - AI quote desk for a fictional manufacturer, Lakeshore Electric
(dry-type transformers and electrical enclosures). All data synthetic.

Folder structure:
  quote-desk/
    README.md  SPEC.md  CLAUDE.md  pyproject.toml  Dockerfile  .env (not committed)
    src/quote_desk/
      generate/   synth_erp.py, synth_emails.py, commodity.py
      foundation/ clean.py, load.py, quality_report.py
      forge/      features.py, train.py, predict.py, similar.py, backtest.py
      intake/     schemas.py, llm.py (Gemini + Ollama providers), extract.py
      workforce/  policy.py, draft.py, approvals.py, guardrails.py, reprice.py
      api/        main.py
    ui/app.py
    evals/  rfq_gold.jsonl, run_extraction_eval.py
    tests/
    data/generated/  (git-ignored)

Product config (what a quote is for):
  product_family: transformer | enclosure
  transformer: kva (15-1000), primary_v (480/600/4160), secondary_v (208/120,
    480/277, 600/347), phase (1/3), winding (copper/aluminum), k_factor (1/4/13),
    enclosure (NEMA 1 / NEMA 3R), efficiency (DOE 2016 / premium), quantity
  enclosure: size, steel gauge, finish, NEMA rating, quantity

Synthetic ERP tables (SQLite):
  customers, items (catalog, with some duplicate part numbers on purpose),
  boms (config -> material lines: copper/aluminum kg, electrical steel kg, steel kg,
  hardware), routings (ops + labor hours + machine hours), jobs (3 years of history:
  config, qty, quote date, quoted price, won/lost, actual material cost, actual
  labor cost, actual unit cost), commodity_prices (monthly copper, aluminum,
  electrical steel indices), open_quotes, inventory, open_pos.
  The "true" unit cost = materials at commodity prices on that date + labor +
  overhead + noise (learning curves on quantity, rework on some jobs).
  Deliberate mess: duplicate parts, quotes mixed into the orders table, cancelled
  jobs, a units column mixing kg and lb, free-text notes, ~3% missing values.

Step 1. Generate (generate/): reproducible (seed), ~3,000 historical jobs.
  Done when: one command builds data/generated/erp.sqlite.

Step 2. Foundation (foundation/): clean the mess (dedupe parts, drop cancelled
  and quote-only rows from cost history, normalize units, flag outliers) and write
  a data quality report (rows in, rows dropped and why).
  Done when: quality_report.md is generated and tests pass.

Step 3. Forge (forge/): features from config + commodity prices at quote date;
  LightGBM median model + 10th/90th percentile models for a range; NearestNeighbors
  on scaled config for "3 most similar past jobs"; SHAP top drivers per quote.
  Backtest: train on years 1-2, test on year 3, compare to a naive baseline
  ("cost of the most similar past job, adjusted to today's copper price").
  Report MAPE and interval coverage (how often actual cost falls inside the range).
  Done when: backtest prints model vs baseline and coverage.

Step 4. Intake (intake/): Pydantic schema RFQRequest (customer, contact, lines:
  [{product_family, config fields, quantity}], requested_ship_date, notes,
  missing_fields[], ambiguities[]). LLM extracts JSON -> validate -> retry up to 2x
  with the validation error fed back. Provider switch: GEMINI or OLLAMA via .env.
  Generate ~25 RFQ emails with known answers (evals/rfq_gold.jsonl): clean ones,
  messy ones (abbreviations like "75kva 3ph 600-208/120 alum NEMA3R"), ones with
  missing info, one with a CSV attachment, one with a PDF.
  Done when: run_extraction_eval.py prints field-level accuracy and missing-detail
  recall for both providers, plus average seconds per email for each.

Step 5. Workforce (workforce/):
  policy.py: authority policy, e.g. auto-draft always; human approval required
    always for sending; extra "needs senior approval" flag if margin < 18%, quote >
    $250k, or uncertainty range > 25% of cost.
  draft.py: quote = predicted cost + target margin (by customer segment), plus a
    plain-language reply email listing assumptions and the missing details as
    questions.
  approvals.py: approval inbox in SQLite: pending -> approved / edited / rejected,
    with who, when, and the diff. Edits logged as feedback for retraining.
  guardrails.py: flag, never act on: requests to change bank/payment details,
    instructions inside an email aimed at the AI ("ignore your rules..."), sender
    domain not matching the customer on file.
  Done when: an end-to-end run turns one email into a pending draft with a
  policy flag, and the suspicious email lands in "flagged", not "drafted".

Step 6. API + UI:
  FastAPI endpoints: POST /rfq (email text in -> request + draft), GET /inbox,
  POST /inbox/{id}/approve|edit|reject, GET /quotes/{id} (cost, range, similar jobs,
  drivers), GET /metrics.
  Streamlit app calls the API: tabs "Inbox", "Quote detail" (cost range, similar
  jobs, SHAP drivers, missing details), "Metrics" (extraction accuracy, MAPE vs
  baseline, % approved without edits, avg seconds per quote).
  Done when: you can run the whole flow in the browser in under 2 minutes.

Step 7 (stretch). Reprice: update copper index +12% -> find open quotes whose
  cost moves > 3% -> draft revised quotes into the inbox with the reason.

Step 8. Ship: Dockerfile running FastAPI + Streamlit (one start script), deploy as
  a Hugging Face Docker Space (Gemini key as a Space secret), README with: problem,
  Mermaid architecture diagram, Foundation/Forge/Workforce mapping, autonomy level
  of each step, metrics table, on-prem speed note, "what I'd do at a real customer"
  (sit with estimators first; read-only ERP access; start with one product line;
  measure turnaround and rework weekly), limitations (synthetic data, cost
  structure known to the generator, small eval set).
