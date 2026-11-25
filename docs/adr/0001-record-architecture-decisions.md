# 1. Record architecture decisions

Status: Accepted (2026-11-24)

## Context
The project is built in public by one developer who must be able to explain every
choice. Reasons get lost in chat logs and commit messages.

## Decision
Keep short Architecture Decision Records in `docs/adr/` in Michael Nygard's format
(Context, Decision, Status, Consequences), numbered, never deleted; a changed mind
gets a new ADR that supersedes the old one.

## Consequences
Every milestone that introduces a decision adds an ADR. Reviewers can read the "why"
in a few minutes.
