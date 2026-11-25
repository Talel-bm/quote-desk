# QuoteDesk: specification (v3)

An AI quote desk for a fictional two-plant electrical-equipment group. Requests for
quote (RFQs) arrive by email and EDI. The system reads them, prices them with an honest
cost range, a delivery promise and a win curve, drafts the quote and reply, and holds
everything for a human "yes". Named agents then keep working over simulated days:
follow-ups, repricing when metal moves, and supplier-delay impact. Every action is
recorded in a tamper-evident log.

All company data is synthetic, produced by a day-by-day world simulator that keeps a
sealed answer key. Metal prices, producer price indexes, wages, exchange rates and order
indexes are real public series. Every number the project reports has a baseline, a
confidence interval and a label: **Measured**, **Derived** or **Projected**.

Positioning: one workflow, built end to end and measured honestly. The engine is generic,
each data source gets a reviewed contract, approval rules are data, and the system runs on
local open models, a hosted model, or a scripted fake.

Design rationale: `docs/architecture.md` and `docs/adr/`. Spec v2 is in git history.

---

## 0. Glossary (plain language)

| Term | Meaning |
|---|---|
| RFQ | Request for quote: "what would this cost and when can you ship?" |
| Estimator | The person at the plant who prices RFQs today, from spreadsheets and memory |
| BOM / routing | The materials a product needs / the shop operations and planned hours to build it |
| Should-cost | What a product *should* cost: its BOM at known prices plus planned hours at labor rates |
| Actual cost | What the finished job really cost (known only for won, shipped jobs) |
| Hit rate | Share of quotes that become orders |
| Lead time / promise date | Order-to-shipment time / the ship date promised to the customer |
| CTO / ETO | Configure-to-order (options from a menu) / engineer-to-order (custom design work) |
| PO, EDI 850 | Purchase order; the standard text format companies use to send one |
| Contract | A reviewed YAML file describing one data source: tables, keys, links, types, units, mappings |
| Ontology | The shared model of the business: object types, links between them, actions on them |
| Conformal calibration | Adjusting a cost range so that "80% of actual costs fall inside" is actually true |
| Pre-registration | Writing down the pass rule *before* running the test, so results can't be tuned |
| Sealed world | A second simulated world, generated once and opened only for the final evaluation |
| Autonomy level | How much an action may do alone: answer, draft, act within rules, coordinate over time |
| M / D / P | Measured (computed by this code on this data) / Derived (computed from measured numbers) / Projected (an estimate) |

---

## 1. The world: Lakeshore Group

### 1.1 Shape

| | North plant (original) | Québec plant (acquired mid-history) |
|---|---|---|
| Families | dry-type transformers, enclosures, panelboards | switchboards, control panels (UL/CSA 508A) |
| Source system | SQLite ERP | Excel workbooks + JSON order export, delivered monthly |
| History | 3 years (2023-11 to 2026-11) | from its acquisition date (~18 months) |
| Conventions | English, USD, kg/lb mix, `LK-` part numbers | French/abbreviated columns, CAD, metric, own numbering |
| Orders arrive as | email (body, PDF spec sheet, Excel BOM, CSV) | email + EDI 850 |

Size (one seed): ~150 customers (~40 buy from both plants under name variants), ~30
suppliers, 6 work centers per plant, ~4,500 quotes, ~150-250k world events. Québec buys
enclosures from North (an intercompany flow: a Québec PO is a North sales order).

### 1.2 Product families

| Family | Type | Config attributes | Main cost drivers | Why it is hard |
|---|---|---|---|---|
| Dry-type transformer | CTO | kVA 15-1000, primary/secondary V, phase, winding Cu/Al, K-factor, NEMA 1/3R, efficiency | copper or aluminum, electrical steel, winding hours | metal moves, rework, rare options |
| Enclosure | CTO | size, gauge, finish, NEMA | sheet steel, cut/weld/paint | setup dominates small runs |
| Panelboard | CTO | amps 100-800, V, phase, circuits, main breaker/lugs, bus Cu/Al, mounting | purchased breakers, copper bus, wiring | component prices and supplier slips |
| Switchboard | CTO/ETO | amps 800-4000, sections, bus, main device, metering, kA | copper bus, large breakers, assembly | few, large, varied jobs |
| Control panel | ETO | I/O points, PLC size, starters/drives, HMI, enclosure | engineering hours, components, wiring | engineering effort varies; little history |

### 1.3 How the world runs (generator-only rules)

The world is a daily loop with an event queue. Every entity draws from its own seeded
random stream, so removing one shock changes only what that shock caused. Every state
change is a world event linked to its cause.

- **Demand:** daily RFQ arrivals ~ Poisson(base × new-orders index `A35SNO` × customer
  seasonality × scenario surge).
- **Estimators (pre-registered in ADR 0015, before any re-measurement):** quote from
  habits, not from the true formula: anchor on the last similar job's price, metal prices
  updated quarterly, learning curve ignored, a per-estimator bias, noise that grows with
  workload, systematic under-estimation of rare options and ETO engineering hours.
- **Pricing and winning:** markup by segment from the plant's price list; the customer
  responds after a delay; p(win) = logistic(a_seg − b_cust · log(price / competitor
  price) − c · (quoted lead − market lead)), where the competitor price carries its own
  noise around true cost. This makes the winner's curse real and keeps margins
  believable (pass bands in `world check`).
- **Supply:** promised date = supplier lead time; true arrival = promised + slip
  (supplier distribution × Philly Fed delivery-time index × scenario disruption). A slip
  is announced (`po_date_changed`) only with probability q: some slips are silent.
- **Capacity:** weekly hours per work center; load above 100% becomes overtime (labor
  ×1.5) up to a cap, then backlog. A job starts when its pegged PO lines have arrived.
  Lead time and overtime come out of the queue, they are not drawn.
- **Actual cost:** Σ material qty × price actually paid (index + supplier spread) +
  Σ actual hours × rate × overtime + rework + rare overrun; every component stored in
  `truth/cost_decomposition`.
- **Acquisition:** the Québec plant appears on a dated `acquisition_closed` event and
  starts delivering monthly exports; one delivery carries a schema change (a renamed
  column, a column that changes unit).

### 1.4 Real public series (IDs verified on 2026-11-24)

| Series | ID / source | Drives |
|---|---|---|
| Copper, aluminum, iron ore | World Bank Pink Sheet (in repo) | metal prices; electrical steel stays synthetic (no public index) |
| Copper wire & cable PPI | FRED `WPU10260314` | wire, bus |
| Cold-rolled steel sheet PPI | FRED `WPU10170710` | enclosure steel |
| Steel mill products PPI | FRED `WPU1017` | general steel |
| Transformer / switchgear PPI | FRED `PCU335311335311P`, `PCU335313335313` | realism checks on price levels |
| New orders, electrical equipment | FRED `A35SNO` | RFQ arrival rate |
| Production, capacity use | FRED `IPG335S`, `CAPUTLG335S` | realism checks |
| Manufacturing wages | FRED `CES3000000008` | labor rate trend (replaces flat 4%) |
| Delivery times (Philly Fed) | FRED `DTCDFSA066MSFRBPHI` | supplier slip pressure |
| CAD/USD | FRED `DEXCAUS` | Québec currency |

A real dated shock inside the window: the July 2025 US tariff on semi-finished copper,
which opened and then collapsed a US vs world copper price gap. Modeled as scenario
`copper_tariff_2025` with documented points. Provenance for every series goes in
`data/raw/README.md`.

### 1.5 Scenarios

Dated shocks in reviewed YAML files (`scenarios/*.yaml`). History contains past ones;
`world advance` plays future ones.

| Scenario | What happens | What the platform should do (scored against truth) |
|---|---|---|
| `copper_tariff_2025`, copper rally | metal prices move (real data) | reprice firm open quotes; leave index-linked ones |
| `winding_slowdown` | North winding center at 70% for 3 weeks | revise promise dates |
| `breaker_supplier_slip` | one supplier slips 14+ days | "N jobs affected, K at risk", exact vs `truth/causes` |
| `datacenter_surge` | demand spike | triage, capacity-aware promises |
| `acquisition_day` | Québec exports start | onboard the source; matching scored live |
| `bank_detail_fraud`, injected instructions | attack emails | flag; never act |

### 1.6 Sealed answer key and deliberate mess

`truth/` (never read by product code; enforced by import rules) holds:
`latent` (customer, supplier, work-center traits; win parameters), `causes`
(effect event → cause event → mechanism), `cost_decomposition`, `crosswalk` (true
cross-plant customer and part links), `ledger` (every planted error: source, table,
key, column, kind, original, corrupted, detectability, single/multi-source,
schema/value level), `doc_labels` (for each document, only the fields it *shows*, with
character spans or cell references).

Planted mess: duplicate part numbers, quote/cancelled rows in jobs, unit mix, ×10 typos,
blanks, customer name variants across plants, currency mix, the schema-change delivery,
a volume drop, late-arriving rows, silent supplier slips. Mess uses its own random
stream, so the clean world underneath is identical.

### 1.7 Documents the world emits

Rendered from world objects; labels come from the world, never from an LLM.
RFQ emails (.eml; English and Canadian French; formal, terse, abbreviated
"xfmr 75kVA 480D-208Y/120"), PDF spec sheets with a title block and ratings table,
customer Excel BOMs (merged headers, header not on row 1, mixed units), CSV line lists,
EDI 850 orders (PO price may differ from quote: an exception to catch), supplier quote
PDFs, attack emails with labeled `attack_kind`. An optional LLM paraphrase is kept only
if every labeled value is still found by code.

---

## 2. What the system does

```
inbox (.eml, EDI) ─▶ Intake ─▶ Forge ─▶ pricing + policy ─▶ approval inbox ─▶ outbox
                       ▲         ▲                 ▲                │
                       └── Foundation ontology ────┘     agents over simulated time:
                          (cleaned, matched, traced)     follow-up, reprice, supply impact
```

1. **Foundation** onboards each source under a reviewed contract into one ontology.
2. **Intake** turns a message into an `RFQCase` where every field has a value, a status
   and its provenance.
3. **Forge** prices each line: should-cost, cost range, lead time, win curve, similar
   jobs, drivers, or "needs an estimator" when the request is outside what it knows.
4. **Workforce** agents draft, apply the authority policy, and route to the inbox; a
   human approves every send; agents keep working as simulated days pass.

---

## 3. Architecture (summary; details in `docs/architecture.md`)

```
src/quote_desk/
  core/        shared Pydantic types: Money, Provenance, Metric, event types, Clock protocol
  config.py    pydantic-settings
  generate/    the world simulator (product code never imports it; evals/ and tests may)
  connectors/  one reader per format (sqlite, csv, xlsx, json, edi850), registry dict
  products/    one module per family: config schema, synonyms (en/fr), standard ratings
  storage/     app.sqlite: migrations, event store, projections, jobs
  foundation/  contracts (YAML), engine, ontology, mapping, matching, observability, trace
  forge/       should-cost, models, conformal, backtest, explain, registry
  intake/      envelope, router, handlers, extract, normalize, status, screen
  workforce/   agents (pure), policy, pricing rules, impact, invariants (no I/O)
  services/    use cases + dispatcher: the only place that runs agents' commands
  api/         FastAPI + SSE
web/           React + Vite + TypeScript + Tailwind + shadcn/ui + Recharts (CoverageCheck stack)
evals/         every evaluation against truth; the only code that may read truth/
```

Layer rule (import-linter): `api → services → workforce | intake | forge → foundation →
connectors | products | storage → core | config`. `workforce`, `intake` and `forge` are
independent of each other: agents return commands, and `services` executes them by calling
intake or forge. No product package imports `generate`.

Stores: `foundation.duckdb` (analytical: cleaned tables, ontology, runs, metrics,
incidents, crosswalk); `app.sqlite` (transactional: one global hash-chained event log,
projections, jobs, timers, journal, outbox, llm_calls); `models/<id>/`; `truth/`.

---

## 4. Build plan

Budget: ~85 hours, 2026-11-25 to 2026-12-01; interview 2026-12-02. Each step is a branch
`step-N-<name>`, merged `--no-ff`. Steps 0-1 of v1/v2 (generate, foundation v1) are done.

### Working method for every step (adapted from CoverageCheck)
1. Read this spec's section; survey the real data with small scratch scripts.
2. Show a short plan with the decisions that need the owner; wait for approval.
3. Code in small pure functions with docstrings that say why; review outputs by hand.
4. Tests: unit tests per rule, real-data tests, exact hand-checked cases, a "never again"
   test for every bug, then a mutation check (break each rule, confirm a test fails).
5. **One** independent audit agent per step (read-only, scratch outside the repo, given
   the owner's decisions so it doesn't re-argue them). Verify every claim on real data
   before acting; show the owner a fix / record / reject table.
6. Update the step's status in this spec (decisions, measured numbers, limits), explain
   each new function in plain language, commit.

Definition of done for every step: CI green (ruff, mypy, import rules, pytest, vitest,
tsc), docs and ADRs updated, numbers labeled M/D/P.

### Step 3. Base + walking skeleton (day 1, ~10 h)
- CI (GitHub Actions: uv, ruff, mypy, lint-imports, pytest with coverage, frontend
  build, docker build), import-linter contracts, pydantic-settings.
- `core/events.py`, `storage/events.py` (global log, hash chain, triggers),
  `storage/projections/`, `storage/jobs.py`, `services/worker.py`.
- Web shell ported from CoverageCheck (SSE helper, Dockerfile, `deploy/space.py`);
  Streamlit removed.
- Thinnest version of each layer: intake with the Fake provider, Forge baseline
  (similar job adjusted to today's copper), policy YAML with two rules, inbox page.
Done when: on the deployed Space, a pasted email becomes a run that streams its steps and
lands in the inbox; approving fills the outbox; a forced forbidden import fails CI.

### Step 4. World v2 (day 2, ~12 h)
Modules under `generate/world/` (`engine`, `market`, `supply`, `shop`, `scenario`),
`generate/families/*` (config sampler, BOM rule, routing rule; same three functions each),
`generate/emit/` (`erp_north`, `exports_qc`, `edi`, `documents`), `generate/mess/`,
`generate/truth.py`. World events also exported as OCEL 2.0 SQLite (should).
Commands: `quote-desk world build --seed N [--without SCENARIO]`,
`world advance --days N [--scenario NAME]` (new documents land in `data/generated/inbox/`,
outbox replies are answered by the world's customers), `world check`.
Pass criteria (`world check`):
- invariants 100% (ship ≤ order, no use before receipt, ids exist, per-object time order);
- same seed → identical file hashes; `--without X` leaves ≥ 95% of causally unrelated
  objects identical;
- stylized facts within bands, each labeled with its source or "assumed": hit rate
  20-50% per segment; won-job median markup within 5 points of intended; loss-making won
  jobs < 8%; supplier on-time 80-95% outside disruptions; lead-time order by family;
  monthly RFQs vs `A35SNO` correlation > 0.5;
- learnability: on cost, LightGBM between the oracle and the best baseline; on lead
  time, backlog features beat a family median by ≥ 20% MAE; no single column within 2
  points of the oracle (leakage test);
- the estimator baseline is *not* near-oracle: oracle WAPE at least 3 points better
  (pre-registered in ADR 0015; if it fails, the miss is reported, not tuned).

### Step 5. Foundation v2 (day 3, ~11 h)
- Contracts as YAML (ODCS v3.2 subset + `customProperties`: mappings, identity, units,
  outlier groups, dataset filters, schema policy), validated by Pydantic; nothing is
  executed when loading. The North contract is converted; `draft-contract` writes YAML.
- `foundation.duckdb` with `deliveries`, `runs`, `metrics`, `incidents`, `match_pairs`,
  `crosswalk`, `mapping_proposals`; every canonical row carries source system, file,
  locator and delivery id.
- Connectors: xlsx (header-row detection, merged cells), json (nested → child tables),
  edi850, csv, sqlite; one shared test suite all must pass.
- `ontology.yaml`: object types (Customer, Item, Quote, QuoteLine, Job, BomLine,
  RoutingOp, WorkCenter, PurchaseOrder, Supplier, PriceIndex, Plant), link types, action
  types (`confirm_match`, `approve_mapping`, `publish_contract`, which are events in the
  same log as quote approvals). Materialized as `obj_*` / `link_*` tables; Forge and
  Workforce read only through `foundation/query.py`.
- Onboarding: `quote-desk connect --source PATH --name qc` → profile → candidates → LLM
  rerank → `ColumnMapping(column, object, property, transform: <registry name>, params,
  confidence, rationale)`. The LLM picks a transform by name and never writes code; a
  human approves each mapping; `contract publish`.
- Matching customers and parts: exact pass, then Fellegi-Sunter with EM and blocking;
  bands auto-match / review / auto-reject; precedence human → rules → model; the review
  queue is ordered by uncertainty.
- Observability: per-run metrics compared with history; incidents for freshness,
  volume, schema, distribution.
- `quote-desk why <ref>`: from a cleaned value (later, from a quote's P50) back to the
  raw file, sheet and cell, with the transforms applied.
Pass criteria: contracts validate against the ODCS JSON Schema (100%); two-stage mapping
top-1 ≥ 0.85 and ≥ 15 points above name-fuzzy on Québec; customer match F1 ≥ 0.95 with
≤ 10% of pairs in review; part match F1 ≥ 0.85; planted incidents detected 4/4 with
≤ 1 false alarm per 10 clean deliveries; ontology counts reconcile exactly; `why`
reproduces 50 random cells 100%; per-error-kind recall ≥ 0.9 or a written reason.

### Step 6. Forge (day 4, ~12 h)
- `should_cost.py` (prices published before the quote date); `bom_model.py` learns
  material quantities and hours from the item master, so new configurations get a
  should-cost too.
- `features.py`: one builder for train and serve; each feature declares `known_at`.
- `cost.py`: LightGBM P10/P50/P90 on log(actual / should-cost), one global model with
  family as a feature; monotone constraints only on the point model.
- `conformal.py`: conformalized quantile regression, per-family where enough rows,
  shrunk toward the group otherwise; quantiles sorted.
- `leadtime.py`: the same pipeline on log(lead days), trained on matured cohorts.
- `win.py`: logistic bid-response model with calibration; `pricing.py`: win curve,
  expected margin, P(loss), quantity breaks. Advice only; never auto-priced.
- `coldstart.py`: Québec families start from should-cost × group ratio, shrink toward
  their own data as months accrue.
- `abstain.py`: outside the training range, unseen level, or far from every past job →
  `NeedsEstimator(reason)`.
- `explain.py`: should-cost breakdown in money, learned factors (×1.07 from size), 3-5
  similar jobs re-indexed to today's prices.
- `backtest.py`: rolling origin, training only on jobs **shipped** before each cut-off;
  outlier flags recomputed inside each window; no after-the-fact columns.
- Baselines: family cost per size, should-cost alone, similar job × copper, kNN, linear,
  **estimator-implied cost**, and the generator oracle (evals only).
- `registry.py`: `models/<id>/` with model files, calibration, feature list, data hash,
  metrics and a generated model card; champion pointer; promotion gate.
Commands: `forge train`, `forge backtest`, `forge truth-check`,
`forge scenario copper=+12% --verify`, `forge coldstart-curve`, `forge promote`.
Pass criteria (in `evals/preregistration.yaml` before the first scored run):
- cost P50 beats the best baseline *and* estimator-implied on WAPE: paired block-bootstrap
  95% CI of the difference excludes 0; "gap closed to oracle" reported;
- 80% range: binomial 95% CI of realized coverage contains 0.80, overall and for each
  family with n ≥ 100; width reported with it;
- truth-check: ≥ 80% of configurations with ≥ 5 test jobs have true coverage in
  [0.70, 0.90];
- lead time: promise reliability CI contains 0.80;
- win model: Brier better than base rate (CI), calibration slope in [0.8, 1.2];
- scenario copper +12%: predicted open-book cost change within ±2 points of the
  re-simulated truth;
- cold start: the curve of Québec accuracy vs months of history is reported;
- leakage tests pass (no feature known after the quote date; label dates before origin);
- promotion requires the paired CI on interval score to exclude 0.

### Step 7. Intake (day 5, ~11 h)
- `envelope.py` (headers, trusted authentication results, body without quoted history,
  attachments with hashes), `router.py`, handlers: `edi850` and `sheet` are deterministic
  code (line F1 must be 1.0), `pdf` (pdfplumber tables, pypdf text), `text` (LLM).
- Two-stage extraction: list the lines, then fill a small schema per line; schemas
  flattened for small models; Pydantic validation and up to 2 re-asks; every call in
  `llm_calls`.
- `normalize.py`: units, en/fr synonyms from `products/`, catalog and crosswalk grounding,
  closest standard rating rounding **up** only (70 kVA → 75 kVA, recorded as a reason).
- Every value is a `FieldValue(raw, value, status ok|check|conflict|missing, reasons,
  provenance[msg, part, locator, quote, method])`. Customer identity comes from code
  (sender domain on file), never from the LLM.
- `screen.py`: payment-detail change, instructions aimed at the AI, look-alike domain.
- Providers: `rules` (no LLM baseline), `fake`, Ollama (`qwen3.5:4b`, `qwen3.5:9b`,
  `qwen2.5:3b` as the old reference), Gemini (`gemini-3.1-flash-lite`,
  `gemini-4-hydrogen`). Tags verified on the demo machine before freezing.
- Sets: dev (tuning), adversarial (each attack with a clean twin and harmless
  look-alikes), and a **blind held-out set of ~80 documents written by independent
  agents** from world configs, frozen before any system sees it.
Commands: `make-rfqs --set`, `intake PATH.eml`, `eval-intake --set --providers`,
`intake-report`.
Pass criteria (fixed before opening held-out): deterministic channels line F1 = 1.00;
valid output after re-asks ≥ 99% hosted, ≥ 97% local ≥ 4B; invented values on absent
fields ≤ 1% hosted; green fields correct ≥ 98% with CI; best LLM arm beats `rules` on
straight-through rate (paired CI); missing-field question recall ≥ 95%; adversarial:
0 consequential actions, field integrity vs clean twin ≥ 95% hosted, false flags on
look-alikes ≤ 10%. Errors scored as correct / wrong / missed / invented; CIs clustered
by document.

### Step 8. Workforce (day 6, ~12 h)
- Event bus on the global log: agents `intake`, `costing`, `quote`, `followup`,
  `repricing`, `supply` each export `SUBSCRIBES` and a pure `handle(event, view) ->
  commands`. The dispatcher (in `services`) processes one event per transaction: run the
  agent, execute its commands, append events, set timers, stage outbox rows, advance the
  agent's cursor. LLM calls and sends go through a journal so a crash never repeats them.
- Simulated clock and timers; follow-up after 7 days without reply; expiry at
  `valid_until`; approvals expire, and the sender re-checks a facts hash before sending.
- Authority policy (`policy/authority.yaml`): permit/forbid with default deny and forbid
  winning; rules carry an id, a closed-vocabulary condition list, and a citation to a
  section of a written pricing-authority memo; action tiers info / commit / commercial /
  financial; presets cautious / balanced / autonomous; payment-detail changes are
  financial and forbidden in every preset; no agent may approve a send.
- `policy simulate --candidate FILE --since DATE`: which past decisions would change.
- Pricing rules: markup by segment from the policy, validity window, firm vs
  index-linked basis.
- Repricing: driven by the real monthly copper print; explodes open quotes' BOMs to
  their metal content; firm quotes only (index-linked adjust at shipment); options with
  recovered dollars and win-probability change.
- Supply impact: from a slipped PO line through pegging and BOMs to jobs (both plants
  via the crosswalk), stock coverage, P80 lead time vs due date → "N affected, K at
  risk", with options.
- `invariants.py` (independent of the policy code) and `sim fuzz`: random crashes at
  named points over 200 seeds.
- `sim run scenarios/ten_days.yaml --preset P`: ~25 RFQs, the fake bank email, an
  injection inside a PDF, a copper print crossing the repricing line, a supplier slip,
  a policy change simulated then approved, a stale approval caught, a "tired" reviewer
  persona triggering an alarm, a checkpoint. Scored against doing nothing and a manual
  desk using the world's own win function (labeled Measured in simulation / Projected).
- Audit: `audit verify` checks the chain; a checkpoint of the chain head is written
  outside the database, so a full rewrite is still detected.
- `eval-workforce`: ~30 tasks scored on final state, required steps in order and
  forbidden actions; reliability pass^4 with the Fake; an attack set.
Pass criteria: `sim fuzz` finds 0 violations (send without fresh approval, duplicate
send, agent approval, stuck process, chain break); same seed → identical final chain
head; `policy simulate` equals a brute-force recomputation; pass^4 ≥ 0.9 with the Fake;
0 consequential actions under attack; supply impact precision and recall ≥ 0.8 on 20
generated slips; five hand-made mutants each caught.

### Step 9. Operations app (day 7, ~11 h)
Pages (built after ASCII options are approved by the owner, and looked at before commit):
- **Inbox**: buckets Ready / Needs senior / Flagged / Waiting; keyboard j/k/a/e/r;
  split view.
- **Quote detail**: every AI-filled value with an `AI` label and its source; should-cost
  breakdown, range, drivers, similar jobs, promise date, win curve; the policy rules that
  fired with their citations; draft diff; history.
- **Runs + Replay**: each run's steps live over SSE (LLM calls, tokens, retries); the
  10-day replay with a day scrubber, using the same reducer as live.
- **Sources**: connect-a-source wizard (upload → profile → mappings → review → dry run
  → publish → scorecard), incidents per delivery.
- **Policy**: YAML, validate, simulate on history, approve as an event.
- **Models / Evidence**: baseline ladder with CIs, coverage by quarter and family, model
  card, intake and workforce eval tables, every number with its M/D/P chip.
- Stretch: Data model explorer, live architecture graph, Audit page, Ctrl-K palette.
Rules: every number comes from the API or a generated JSON checked by a freshness test;
no numeric LLM confidence; "flagged" is a normal state; TypeScript types generated from
OpenAPI with a drift check; 3 Playwright flows that also produce the README screenshots.

### Step 10. Seal, measure, ship (day 8, ~6 h)
- `evals/preregistration.yaml` and the sealed world's profile hash are committed before
  the freeze tag; the sealed world is generated with a different seed and a perturbation
  profile chosen by a separate agent from a documented menu.
- `quote-desk eval --sealed` runs every layer once and writes `evals/results.json`; the
  README results block and the Evidence page are generated from it.
- Deploy: public Space with the Fake provider and the recorded replay by default, a live
  model behind a per-visitor gate; an on-prem compose file (app + Ollama) and
  `bench-llm` latency table on named hardware (Measured).
- README: problem, 5-minute demo path, architecture diagram, the 10 numbers, limits,
  "first 30 days at a customer" playbook.

### Roadmap (designed, built after the interview)
Merkle inclusion/consistency proofs; autonomy promotion from override data; missing-
information clarification loop over email threads; scanned PDFs with a vision model;
Spanish; local-then-hosted cascade; online conformal through drift; supplier-delay
model per supplier; incremental deliveries with replay = rebuild; contract diff with
breaking-change severities; active learning and an LLM judge for matching; a held-out
third source for mapping; invoices, payments, quality and engineering-change events;
EDI 855/856/810; steward agent; perturbed-worlds robustness table.

---

## 5. Evidence protocol

- **Pre-registration:** per layer, the primary metric, comparison, pass rule, n and CI
  method in `evals/preregistration.yaml`, committed before the measured run. A changed
  threshold is a new commit with a reason; reports show both.
- **Dev vs final:** tune on dev sets and the dev world only; the sealed world and the
  intake held-out set are opened once, after the freeze tag; gold exposure is logged.
- **Statistics:** block bootstrap by month for Forge, clustered by document for Intake,
  paired comparisons between systems; every number is a
  `Metric(value, ci_low, ci_high, n, label, source)`.
- **The 10 numbers:** (1) cost WAPE vs best baseline and vs estimators, gap closed to
  oracle; (2) 80% range coverage and width; (3) share of lines drafted at the estimator's
  error level (risk-coverage curve); (4) held-out extraction accuracy, local vs hosted;
  (5) attack emails flagged and unsafe actions (0); (6) planted errors caught per kind;
  (7) cross-plant match F1; (8) repricing exposure precision/recall and margin recovered;
  (9) 10-day replay vs doing nothing and manual; (10) latency and cost per RFQ, and the
  cost of onboarding a new source.

## 6. Safety design

- The extracting model has no tools and returns typed data; the drafting step never sees
  the raw email. Prices, recipients and bank details come from code and data.
- A human approves every outgoing email; the outbox is filled only from a fresh approval
  event; agents can never approve.
- Payment-detail changes are financial-tier and forbidden in every preset: flagged with
  "verify by phone using the number on file".
- Injection heuristics only raise flags; the defense is the structure above, tested with
  an attack suite in CI.
- Threat model in `docs/architecture.md`.

## 7. Non-goals

LangChain or agent frameworks; autonomous sending; LLM-set prices; LLMs inside Forge's
predictions; a graph database or RDF; Postgres, Kafka, Celery, MLflow, Kubernetes; deep
tabular networks; real company data; claims of being injection-proof.

## 8. Stack

Python 3.12, uv. Runtime: pandas, numpy, LightGBM, scikit-learn, SHAP, FastAPI (native
SSE), uvicorn, google-genai, ollama, pypdf, pdfplumber, httpx, faker, python-dotenv,
pydantic-settings, pyyaml, rapidfuzz, fpdf2, openpyxl, duckdb. Dev: pytest, pytest-cov,
ruff, mypy, pandas-stubs, import-linter, hypothesis, syrupy, playwright; pm4py dev-only
(AGPL, never in the image). Frontend: React, Vite, TypeScript, Tailwind, shadcn/ui,
Recharts, Vitest (Node at build time only). Streamlit removed.
