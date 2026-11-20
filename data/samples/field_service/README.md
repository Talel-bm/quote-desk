# Field-service sample (fictional)

A tiny, unrelated dataset (an HVAC service company) used to show that the
Foundation engine is generic: it is cleaned by the same code as the ERP, with
only a different contract (`src/quote_desk/foundation/contracts/field_service_demo.py`).

Mess planted on purpose, which the engine must find without being told where:
one site recorded under two IDs, labor in hours and minutes, a repeated work
order, a work order pointing to an unknown technician, a non-numeric labor
value, cancelled and open orders, missing parts costs, and one parts cost that
is about 10x too high.

Run it with `uv run quote-desk clean --demo` (reviewed contract), or treat it as
brand-new data:

```sh
uv run quote-desk profile --source data/samples/field_service
uv run quote-desk clean --source data/samples/field_service   # drafts a contract first
```
