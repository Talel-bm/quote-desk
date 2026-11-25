# 12. An ontology of object, link and action types, stored as tables

Status: Accepted (2026-11-24)

## Context
With two plants on different systems, downstream code needs one model of the business
("this customer, its quotes, its jobs, the parts they use, the POs feeding them"), not
two sets of tables. Answers over such a semantic layer are measurably better than over
raw tables (Sequeda et al., 2023). A graph database would add infrastructure that nobody
here needs.

## Decision
`foundation/ontology.yaml` declares:
- object types, with keys and typed properties;
- link types, with cardinality;
- action types: `confirm_match`, `approve_mapping`, `publish_contract`.

The file is compiled into Pydantic models and materialized as `obj_*` / `link_*` tables
in DuckDB. Forge and Workforce read only through `foundation/query.py` (`get`,
`neighbors`, `find`). Actions are events in the same log as quote approvals. There is no
RDF, no SHACL and no graph database.

## Consequences
"Every entity and relationship counted" is a command (`ontology stats`) whose counts
reconcile exactly with the sources. Changing the ontology is a reviewed file change.
