# 4. Generic Foundation engine with per-source YAML contracts

Status: Accepted (2026-11-24). Supersedes the Python-file contracts of step 2 once Step 5 lands.

## Context
Step 2 built a generic cleaning engine driven by per-source contracts written as
Python files. Loading a contract therefore runs code, and drafts may later be written
by a program or an LLM.

## Decision
Contracts become YAML files validated by Pydantic, laid out after the Open Data
Contract Standard (tables, columns, keys, relationships, quality rules), with
QuoteDesk-specific parts (identity for duplicates, units, outlier groups, dataset
filters, column mappings to the canonical model) in a custom section. Custom checks
stay in code and are referenced by name. Loading a contract never executes code.

## Consequences
Contracts are safe to load, easy to diff, and can be exported to the standard. The
existing Python contracts are converted once (Step 5); until then both load paths exist.
