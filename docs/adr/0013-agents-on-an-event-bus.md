# 13. Agents as pure handlers on an event bus, run by a single dispatcher

Status: Accepted (2026-11-24)

## Context
Several processes run over days and touch many quotes and jobs at once: follow-ups,
repricing, supplier-delay impact. Workflow engines (Temporal, DBOS, Restate) solve
durability, but they are infrastructure that this project's reviewers would have to
learn. Agent frameworks add behavior nobody here can explain.

## Decision
- **Agents.** Each agent (`intake`, `costing`, `quote`, `followup`, `repricing`,
  `supply`) is a module with `SUBSCRIBES` and a pure `handle(event, view) -> commands`.
- **Dispatcher.** It lives in `services` and processes one event per transaction. It
  runs the agent, executes the commands (calling intake or forge), appends events, sets
  timers, stages outbox rows and moves the agent's cursor.
- **Journal.** LLM calls and sends go through a journal keyed by idempotency key, so a
  crash never repeats them.
- **Time.** A simulated clock drives timers.
- **Crash testing.** `sim fuzz` crashes the loop at random named points over many seeds.
  An invariant checker, written without importing the policy code, must find nothing.

## Consequences
The minimal core of durable execution, in about 300 explainable lines. The README names
which parts Temporal or DBOS would replace at scale.
