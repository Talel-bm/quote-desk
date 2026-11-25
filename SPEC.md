# QuoteDesk: specification (v2)

An AI quote desk for a fictional group of electrical-equipment plants. A customer
request for quote (RFQ) arrives by email; the system reads it, estimates cost with an
honest range, drafts a quote and a reply, and holds everything for a human "yes".
It then keeps working over time: follow-ups, expiry, and repricing open quotes when
metal prices move. All company data is synthetic; metal prices and a few public
price indexes are real.

Positioning: a small, honest, end-to-end version of one industrial-AI workflow.
The engine is generic and each data source gets a reviewed configuration; cost
uncertainty is measured; approval rules are data; every action is recorded; it runs
on open local models or a hosted one; every number is compared with a baseline.

Design rationale lives in `docs/architecture.md` and `docs/adr/`.

---

## 1. Glossary (plain language)

| Term | Meaning |
|---|---|
| RFQ | Request for quote: a customer asks "what would this cost and when can you ship?" |
| Estimator | The person at the plant who prices RFQs today, mostly from spreadsheets and memory |
| BOM | Bill of materials: the list of materials and parts one product needs |
| Routing | The list of shop operations (cut, wind, weld, wire, test) and their planned hours |
| Should-cost | What a product *should* cost from its BOM at today's prices plus planned labor hours |
| Actual cost | What the finished job really cost (only known for won, built jobs) |
| Hit rate | Share of quotes that become orders |
| Lead time | Time from order to shipment |
| CTO / ETO | Configure-to-order (pick options from a menu) / engineer-to-order (custom design work) |
| EDI 850 | The standard text format companies use to send purchase orders |
| Contract | A reviewed file describing one data source: tables, keys, links, types, units, rules |
| Conformal calibration | Adjusting a cost range so that "80% of actual costs fall inside" is actually true |
| Autonomy level | How much an action may do alone: answer, draft, act within rules, coordinate over time |

---

## 2. The fictional world: Lakeshore Group

Two plants. Plant North is the original company (the current generator). Plant South
was acquired 18 months before "today" and runs a different system.

| | Plant North | Plant South (acquired) |
|---|---|---|
| Families | dry-type transformers, enclosures, panelboards | switchboards, control panels (UL 508A) |
| System | SQLite ERP | spreadsheet exports (multi-sheet Excel) + JSON order export |
| History | 3 years | 18 months |
| Conventions | English columns, USD, kg/lb mix, `LK-` part numbers | French/abbreviated columns, EUR, metric only, own numbering |
| Orders arrive as | emails with PDF / Excel / CSV attachments | emails + EDI 850 purchase orders |

Cross-plant facts (hidden truth, scored by the evals): ~30% of customers buy from both
plants under name variants; South buys enclosures from North; ~40% of South's
purchased parts are the same parts North uses under different numbers.

### 2.1 Product families

| Family | Type | Config attributes | Main cost drivers | Why it is hard to predict |
|---|---|---|---|---|
| Dry-type transformer | CTO | kVA 15-1000, primary/secondary V, phase, winding Cu/Al, K-factor, NEMA 1/3R, efficiency | copper or aluminum, electrical steel, winding labor | metal prices move; rework; rare options |
| Enclosure | CTO | size, steel gauge, finish, NEMA rating | sheet steel, cutting/welding/paint | small parts, setup cost dominates small quantities |
| Panelboard | CTO | amps 100-800, voltage, phase, circuits, main breaker vs lugs, bus Cu/Al, mounting | breakers (purchased), copper bus, wiring labor | purchased-component prices and availability |
| Switchboard | CTO/ETO | amps 800-4000, sections, bus Cu/Al, main device, metering, kA rating | copper bus, large breakers, assembly hours | few jobs, large and varied |
| Control panel (UL 508A) | ETO | I/O points, PLC size, motor starters/drives, HMI, enclosure size | engineering hours, components, wiring | engineering effort varies a lot; little history |

Out of scope: CAD-based costing, a full option configurator, more than five families.

### 2.2 Commercial reality the world simulates

- Quotes have revisions, a status, a `valid_until` (30 days by default), a loss reason,
  and a price basis: **firm** or **index-linked** (metal adjusted at shipment).
- Quantity price breaks (setup cost spread over the run).
- Win probability falls as price rises relative to cost; hit rates 20-50% by segment.
- A capacity model: weekly work-center hours with a first-in-first-out backlog, so long
  backlogs cause overtime and late deliveries (lead time becomes predictable data).
- Hidden cost drivers the ERP never records (supplier spread, per-customer extra work,
  shop load, rework, rare major overruns), as today.

### 2.3 Real public data anchoring the world

| Series | Source / ID | Used for |
|---|---|---|
| Copper, aluminum ($/t) | World Bank Pink Sheet | material prices (already in repo) |
| Iron ore | World Bank Pink Sheet | synthetic electrical steel (no public index exists) |
| Copper wire & cable PPI | FRED `WPU10260314` | wire/bus cost trend |
| Cold-rolled steel sheet PPI | FRED `WPU10170710` | enclosure steel |
| USD/EUR | FRED `DEXUSEU` | Plant South currency |
| Electrical-equipment production index | FRED `IPG335S` | demand cycle and shop load |
| Coil-winder wages | BLS OEWS 51-2021 | labor rate level (replaces flat 4%/yr) |

Every series ID is checked when `fetch-commodities` is extended; provenance goes in
`data/raw/README.md`.

### 2.4 Deliberate mess, with an error ledger

Every planted error is written to a hidden ledger: error kind, where, original value,
and two tags (single- vs multi-source; schema- vs value-level, after Rahm & Do 2000).
Kinds: duplicate part numbers, quote/cancelled rows mixed into jobs, unit mix,
x10 typos, blanks, name variants across plants, currency mix, renamed column and a
column that changes meaning at a dated "system upgrade" (schema drift), a volume drop
in the last month, late-arriving rows. The ledger lets Foundation be scored per error
kind (detected? repaired correctly?).

Rule: platform code never imports the generator or reads the ledger; only `evals/`
and tests do. This is enforced in CI (section 4).

---

## 3. What the system does (the workflow)

```
email (.eml + attachments) ──▶ Intake ──▶ Forge ──▶ Workforce ──▶ approval inbox ──▶ outbox
                                 ▲          ▲           │                 │
                          products registry │           └─ processes over time (clock):
                                            │              follow-up, expiry, reprice
                          Foundation (cleaned, unified data from both plants)
```

1. **Intake** turns an email into a validated `RFQRequest` with a status per field.
2. **Forge** prices each line: cost range, lead time, similar past jobs, cost drivers.
3. **Workforce** drafts the quote and reply, applies the authority policy, and puts the
   draft in the inbox. Nothing leaves without a human approval.
4. **Over time**, a simulated clock drives follow-ups, expiries and repricing.

---

## 4. Architecture (summary; details in `docs/architecture.md`)

A modular monolith: one Python package, strict layers, checked by `import-linter`.

```
src/quote_desk/
  core/        shared types (money, ids, clock), no dependencies
  config.py    settings (pydantic-settings), paths, seeds
  generate/    the synthetic world (outside the product; only CLI, tests, evals import it)
  connectors/  one reader per file format, registered by name
  products/    one module per product family: config schema, synonyms, features
  storage/     app.sqlite migrations and repositories
  foundation/  generic cleaning engine + contracts/ (YAML) + entity resolution
  forge/       features, models, calibration, backtest, registry
  intake/      parse, extract (LLM), normalize, screen
  workforce/   policy, draft, inbox, outbox, processes, reprice
  services/    use cases: the only place that calls several layers
  api/         FastAPI
evals/         intake, foundation and forge evals against hidden truth
ui/app.py      Streamlit, talks to the API over HTTP only
```

Dependency rules (top may import bottom, never the reverse):
`api / cli → services → workforce → intake | forge → foundation → connectors | products | storage → core | config`.
`intake` and `forge` are independent. No product package imports `generate`.

Ports (a `typing.Protocol` plus a fake for tests) only at real seams: `LLMClient`,
`SourceReader`, `Clock`, `Mailer`. Decisions (policy, guardrails, cleaning, reprice)
are pure functions.

Storage: SQLite. `erp_*` sources are read-only. `foundation.sqlite` holds cleaned data.
`app.sqlite` holds app state: an append-only, hash-chained `events` table (updates
and deletes blocked by triggers), a `quotes` current-state table written in the same
transaction, an `outbox` table only approved events can fill, and `llm_calls`.

---

## 5. Milestones

Each milestone is a branch `step-N-<name>`, merged with `--no-ff`. Definition of done
for every milestone: CI green (tests, ruff, mypy, import rules), CLAUDE.md and docs
updated, an ADR for any new decision, and a one-paragraph demo script.

**Interview cut (by 2026-12-01): M0-M4.** Everything after is the roadmap.
If time runs short, cut in this order: follow-up/expiry process, hash chain,
per-family calibration.

### M0. Engineering base (0.5 day)
GitHub Actions CI (uv, ruff format+check, mypy, lint-imports, pytest with coverage),
import-linter contracts, pydantic-settings config, ADRs 0001-0009, `docs/architecture.md`.
Done when: CI is green on `main` and a deliberate forbidden import fails CI.

### M1. Walking skeleton (2 days)
The thinnest working version of every layer, connected end to end, deployed.
- `products/`: transformer and enclosure schemas (Pydantic).
- `forge` v0: the baseline only (most similar past job, adjusted to today's copper).
- `intake` v0: `RFQRequest` schema, providers Gemini / Ollama / Fake, validate and
  re-ask up to 2 times with the validation error.
- `workforce` v0: policy rules in YAML, quote draft + reply email, inbox events,
  three guardrails (payment-detail change, instructions aimed at the AI, sender domain).
- `services`, FastAPI (`POST /rfq`, `GET /inbox`, `POST /inbox/{id}/approve|edit|reject`,
  `GET /quotes/{id}`), Streamlit (Inbox, Quote detail), Dockerfile, Hugging Face Space.
Done when: in the deployed app, a pasted email becomes a pending draft with a policy
flag, and the suspicious email lands in "flagged", using the Fake provider without a key.

### M2. Forge v1: cost with an honest range (2 days)
- Should-cost from BOM quantities x commodity price known before the quote date,
  plus routing hours x labor rate (ERP planning data, not generator formulas).
- Target: log(actual / should-cost). One global LightGBM, P10/P50/P90, family as a feature.
- Conformalized quantile regression (hand-written, ~15 lines), calibrated on the most
  recent slice; quantiles sorted to avoid crossing.
- Rolling-origin backtest (expanding window, quarterly origins) against a baseline
  ladder: family cost-per-size, should-cost alone, similar-job x copper, kNN, linear,
  LightGBM, and the generator oracle (evals only).
- Metrics: WAPE, median APE, MAE of log cost, coverage *and* width, interval score,
  sliced by family, size and quarter. Every number labeled Measured / Derived / Projected.
- Similar jobs: 3-5 nearest by Gower distance, shown at today's prices.
- Drivers: SHAP on the log target shown as factors ("x1.18 from copper").
- Model folder `models/<timestamp>-<gitsha>/` (models, conformal.json, features.json,
  data hash, metrics.json, generated model_card.md) + `registry.json` champion pointer.
- Promotion gate as a test: beat the best baseline on WAPE and the champion on
  interval score, coverage within +-3 points.
- Leakage tests: features use only data available at quote time; outlier flags are
  recomputed inside each training window.
Done when: `quote-desk backtest` prints the ladder and coverage, and the inbox shows
range, similar jobs and drivers.

### M3. Intake v1: measured extraction (1 day)
- Four stages, each stored as a trace: parse (.eml, PDF text, CSV/Excel attachment)
  → extract (LLM) → normalize (code: units, synonyms, catalog match) → screen (rules).
- Per-field status ok / check / missing from deterministic signals: the field's source
  quote appears in the email, catalog match exact / fuzzy / none, retries needed.
- 40 generated RFQs with exact answers (English, French, abbreviations, missing info,
  CSV and PDF attachments, 8 attack emails). Labels come from the generator.
- `quote-desk eval-intake`: per-field accuracy, missing-field recall, attack catch
  rate, retry rate, seconds per email, for Gemini, qwen2.5:3b and the Fake.
- `llm_calls` table: provider, model, tokens, latency, attempts, validation errors.
Done when: the eval table prints for all providers and the UI colors fields by status.

### M4. Workforce v1: rules, record, and work over time (1.5 days)
- Authority policy as reviewed YAML: deny unless a rule allows; a forbid beats a
  permit; every decision logs the rule id and its evidence. Senior approval if margin
  < 18%, value > $250k, range wider than 25% of cost, or low-data family.
- Each action type has an autonomy level: answer, draft, act within rules, coordinate.
- Hash-chained events + `quote-desk verify-audit`; outbox only fillable from approval.
- Simulated clock, `quote-desk tick --days N`: follow-up drafts after 7 days without
  reply, expiry at `valid_until`.
- Repricing: `quote-desk reprice --copper +12%` re-prices open quotes; only those whose
  margin falls below policy reach the inbox, with the reason and the change.
- Metrics page: turnaround, % approved without edits, edit size, override and
  escalation rates, flags, plus Forge and Intake eval numbers.
Done when: a scripted demo (`quote-desk demo`) runs RFQs, a copper jump and a fake
bank-detail email, and the metrics page shows the results.

### M5. World v2: the group (1.5 weeks)
Panelboards, switchboards, control panels; Plant South with its own exports (Excel,
JSON), EDI 850 orders, French/EUR/metric conventions; shared customers and parts with
hidden true links; schema drift event; error ledger; capacity and lead-time
simulation; real series from 2.3. One command: `quote-desk world --seed N`.
A learnability check per target (cost, lead time) with oracle, baseline and LightGBM,
and single-column leakage tests (no column alone should give away the answer).

### M6. Foundation v2: many sources, one model (1.5 weeks)
- Connectors registry behind `load_source()`: Excel (header-row detection, merged
  cells), JSON (nested → child tables), fixed-width, EDI 850, CSV, SQLite. Each adds
  `_source_file` / `_source_locator` and a file hash. One shared test suite every
  connector must pass.
- Contracts move to YAML, validated by Pydantic, shaped after the Open Data Contract
  Standard; `draft-contract` writes YAML (nothing is executed when loading).
- Canonical model of ~9 entities (customer, item, BOM line, routing op, work center,
  quote, job, purchase order, price index) with per-contract column mappings.
- Cross-source matching: exact pass, then a hand-written Fellegi-Sunter scorer with
  blocking; uncertain pairs go to review; precision/recall vs hidden truth.
- Quality scorecard by dimension (completeness, validity, uniqueness, consistency,
  timeliness); a `runs` table with row counts, schema fingerprint, latest date and null
  rates, compared run to run to catch drift, volume drops and staleness.
- `quote-desk trace <table> <key>`: where a cleaned value came from.
- Foundation eval: per-error-kind detection and repair scores from the ledger.

### M7. Forge v2: many families, cold start, lead time, win probability (1 week)
Per-family coverage (calibrate per family where >= 200 rows), adaptive conformal
across the copper rally, cold-start fallback for Plant South with an accuracy-vs-
months-of-history curve, leave-one-family-out test, lead-time model with the same
pipeline, advisory win-probability curve (never auto-pricing), winner's-curse study
using the generator's truth for lost quotes, ground-truth coverage per configuration.

### M8. Intake v2 (1 week)
150-300 RFQs including EDI and Excel BOM attachments and scanned-looking PDFs; qwen 7B
added to the comparison; error analysis written up as a failure taxonomy; a red-team
suite of ~30 attack emails run in CI with the Fake and on demand with real models.

### M9. Workforce v2 and the 10-day replay (1 week)
Missing-information clarification loop, quote revisions, supplier-delay impact
("9 jobs affected, 2 at risk"), autonomy promotion suggestions from override data,
a 10-day scripted replay (RFQs, Plant South onboarding, copper jump, supplier slip,
fake bank email) ending on the metrics page. README with the "first 30 days at a
customer" playbook, measured on-prem latency note, limitations.

---

## 6. Evaluation protocol (summary)

| Layer | Truth source | Headline metrics |
|---|---|---|
| Foundation | error ledger, hidden cross-plant links | per-kind detection precision/recall, repair accuracy, match F1 |
| Forge | actual costs (time-split), generator oracle | WAPE vs baseline ladder, coverage + width, per family and quarter |
| Intake | generator labels per document | per-field accuracy, missing-field recall, attack catch rate, latency, cost |
| Workforce | event log | turnaround, % approved without edits, override/escalation rates, follow-up completion |

Every reported number is labeled **Measured** (computed by this code on this data),
**Derived** (computed from measured numbers) or **Projected** (an estimate).

## 7. Safety design (summary)

- The extracting model has no tools and returns typed data only; the drafting step
  never sees the raw email. Prices, recipients and bank details come from code and
  data, never from model output.
- A human approves every outgoing email; the outbox cannot be filled any other way.
- Payment-detail changes are never acted on: flagged, with "verify by phone using the
  number on file". Sender domain must match the customer on file.
- Injection heuristics only raise a flag; the defence is the design above.
- Threat model in `docs/architecture.md` maps each relevant OWASP LLM risk to a
  control and a test.

## 8. Non-goals

LangChain or agent frameworks; autonomous sending; LLM-set prices; a knowledge-graph
database; Postgres, Kafka, Celery, MLflow, Kubernetes; deep tabular networks; more
than five product families; real company data.

## 9. Stack

Python 3.12, uv. Runtime: pandas, numpy, LightGBM, scikit-learn, SHAP, FastAPI,
uvicorn, Streamlit, google-genai, ollama, pypdf, httpx, faker, python-dotenv,
pydantic-settings, pyyaml, rapidfuzz, fpdf2, openpyxl.
Dev: pytest, pytest-cov, ruff, mypy, pandas-stubs, import-linter, hypothesis, syrupy.
