# 8. The model never decides prices, recipients or payment details

Status: Accepted (2026-11-24)

## Context
The system combines untrusted input (emails), sensitive data (costs, margins) and an
external action (sending email): all three conditions for prompt-injection harm.

## Decision
- The extractor has no tools; the drafter never sees the raw email.
- Prices come from Forge and the policy; recipients and bank details come from the
  customer record. Model output cannot set them.
- A human approves every outgoing email (outbox rule, ADR 5).
- Payment-detail change requests are always flagged with "verify by phone using the
  number on file", never acted on. Injection heuristics only raise flags.

## Consequences
The system does not claim to be injection-proof; it is designed so that a successful
injection cannot move money or send anything on its own.
