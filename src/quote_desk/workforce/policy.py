"""The authority policy: who may do what, decided from reviewed rules (ADR 14).

Semantics (the same as the Cedar policy language): an action is allowed only if at
least one `permit` rule matches and no `forbid` rule matches. Default deny; forbid wins.
Conditions use a closed set of operators, so the file never runs code.

"Needs a senior" is not a special outcome: it simply means an estimator is forbidden
and a senior is permitted. `bucket()` turns that into the inbox bucket.
"""

import operator
from collections.abc import Callable
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

OPS: dict[str, Callable[[Any, Any], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
    "in": lambda a, b: a in b,
}


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    op: Literal["<", "<=", ">", ">=", "==", "!=", "in"]
    value: Any


class PrincipalMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["human", "agent"]
    roles_in: list[str] | None = None
    roles_not_in: list[str] | None = None


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    effect: Literal["permit", "forbid"]
    principal: PrincipalMatch
    action: str
    when: list[Condition] = []
    reason: str
    source: str  # section of the policy memo


class Pricing(BaseModel):
    validity_days: int
    default_margin: float
    target_margin: dict[str, float]


class Policy(BaseModel):
    version: str
    source_doc: str
    pricing: Pricing
    rules: list[Rule]


class Principal(BaseModel):
    kind: Literal["human", "agent"]
    role: str


class Decision(BaseModel):
    allowed: bool
    permits: list[str]  # ids of permit rules that matched
    forbids: list[str]  # ids of forbid rules that matched
    reasons: list[str]  # reason + memo section of every forbid that matched


def load_policy(text: str) -> Policy:
    return Policy.model_validate(yaml.safe_load(text))


def principal_matches(match: PrincipalMatch, who: Principal) -> bool:
    if match.kind != who.kind:
        return False
    if match.roles_in is not None and who.role not in match.roles_in:
        return False
    return not (match.roles_not_in is not None and who.role in match.roles_not_in)


def condition_holds(cond: Condition, context: dict[str, Any]) -> bool:
    """A condition on a missing field never holds (it cannot be checked)."""
    if cond.field not in context or context[cond.field] is None:
        return False
    return OPS[cond.op](context[cond.field], cond.value)


def rule_matches(rule: Rule, who: Principal, action: str, context: dict[str, Any]) -> bool:
    return (
        rule.action == action
        and principal_matches(rule.principal, who)
        and all(condition_holds(c, context) for c in rule.when)
    )


def decide(policy: Policy, who: Principal, action: str, context: dict[str, Any]) -> Decision:
    """Allowed only if some permit matches and no forbid matches."""
    matched = [r for r in policy.rules if rule_matches(r, who, action, context)]
    permits = [r.id for r in matched if r.effect == "permit"]
    forbids = [r for r in matched if r.effect == "forbid"]
    return Decision(
        allowed=bool(permits) and not forbids,
        permits=permits,
        forbids=[r.id for r in forbids],
        reasons=[f"{r.reason} (memo {r.source})" for r in forbids],
    )


def bucket(policy: Policy, context: dict[str, Any]) -> tuple[str, Decision]:
    """Which inbox bucket a draft belongs in, and the decision that explains it."""
    action = "quote.approve_send"
    as_estimator = decide(policy, Principal(kind="human", role="estimator"), action, context)
    if as_estimator.allowed:
        return "ready", as_estimator
    as_senior = decide(policy, Principal(kind="human", role="senior"), action, context)
    if as_senior.allowed:
        return "needs_senior", as_estimator
    return "flagged", as_senior


def target_margin(policy: Policy, segment: str) -> float:
    return policy.pricing.target_margin.get(segment.lower(), policy.pricing.default_margin)
