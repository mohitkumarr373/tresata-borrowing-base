"""Pure O(n + d) reconciliation over an approved, narrow rule vocabulary."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .money import floor_rate, money


@dataclass(frozen=True, slots=True)
class Invoice:
    invoice_id: str
    debtor_id: str
    debtor_name: str
    invoice_date: date
    amount: int
    credit: int = 0
    disputed: bool = False
    evidence: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class Rules:
    age_days: int
    cross_age_bp: int
    concentration_bp: int
    advance_bp: int
    reserve: int
    commitment: int
    rule_id: str

    def __post_init__(self):
        if type(self.age_days) is not int or not 0 < self.age_days <= 3650:
            raise ValueError("age_days must be in [1, 3650]")
        for rate in (self.cross_age_bp, self.concentration_bp, self.advance_bp):
            if type(rate) is not int or not 0 < rate <= 10000:
                raise ValueError("Rates must be positive integer basis points, at most 10000")
        for amount in (self.reserve, self.commitment):
            if type(amount) is not int or amount < 0:
                raise ValueError("Reserve and commitment must be non-negative integer cents")


def calculate(invoices: list[Invoice], rules: Rules, as_of: date, reported: int | None = None) -> dict:
    totals, overdue = defaultdict(int), defaultdict(int)
    seen = set()
    for inv in invoices:
        if not inv.invoice_id or inv.invoice_id in seen or not inv.debtor_id:
            raise ValueError("Duplicate invoice or missing invoice/debtor identity")
        seen.add(inv.invoice_id)
        if type(inv.amount) is not int or type(inv.credit) is not int or not 0 <= inv.credit <= inv.amount:
            raise ValueError("Credit allocation must lie between zero and invoice amount")
        if inv.invoice_date > as_of:
            raise ValueError("Future-dated invoice")
        if type(inv.disputed) is not bool:
            raise ValueError("Disputed must be a boolean")
        net = inv.amount - inv.credit
        totals[inv.debtor_id] += net
        if (as_of - inv.invoice_date).days > rules.age_days:
            overdue[inv.debtor_id] += net
    crossed = {d for d, total in totals.items()
               if total > 0 and overdue[d] * 10000 >= total * rules.cross_age_bp}
    remaining, rows = defaultdict(int), []
    gross = credits = union_exclusions = 0
    for inv in invoices:
        net = inv.amount - inv.credit
        age = (as_of - inv.invoice_date).days
        reasons = []
        if age > rules.age_days:
            reasons.append("AGE")
        if inv.disputed:
            reasons.append("DISPUTE")
        if inv.debtor_id in crossed:
            reasons.append("CROSS_AGE")
        excluded = net if reasons else 0
        gross += inv.amount
        credits += inv.credit
        union_exclusions += excluded
        remaining[inv.debtor_id] += net - excluded
        rows.append({"invoice_id": inv.invoice_id, "debtor_id": inv.debtor_id,
                     "debtor_name": inv.debtor_name, "age_days": age,
                     "gross": money(inv.amount), "credit": money(inv.credit), "net": money(net),
                     "excluded": money(excluded), "pre_concentration_eligible": money(net - excluded),
                     "reasons": reasons, "source": inv.evidence})
    pool = sum(remaining.values())
    cap = floor_rate(pool, rules.concentration_bp)
    debtors = []
    eligible = concentration = 0
    for debtor, total in totals.items():
        before = remaining[debtor]
        allowed = min(before, cap)
        eligible += allowed
        concentration += before - allowed
        debtors.append({"debtor_id": debtor, "net": money(total), "overdue": money(overdue[debtor]),
                        "cross_aged": debtor in crossed, "pre_concentration": money(before),
                        "concentration_limit": money(cap), "concentration_exclusion": money(before - allowed),
                        "eligible": money(allowed)})
    advance = floor_rate(eligible, rules.advance_bp)
    before_commitment = max(0, advance - rules.reserve)
    base = min(rules.commitment, before_commitment)
    assert gross - credits == union_exclusions + concentration + eligible
    return {
        "status": "READY_FOR_REVIEW", "currency": "USD", "as_of": as_of.isoformat(),
        "rule_id": rules.rule_id, "gross": money(gross), "credits": money(credits),
        "net": money(gross - credits), "eligibility_exclusions": money(union_exclusions),
        "pre_concentration_pool": money(pool), "concentration_exclusions": money(concentration),
        "eligible": money(eligible), "advance": money(advance), "reserve": money(rules.reserve),
        "commitment": money(rules.commitment), "base": money(base),
        "reported": money(reported) if reported is not None else None,
        "variance": money(reported - base) if reported is not None else None,
        "invoice_count": len(rows), "debtor_count": len(debtors),
        "invoices": rows, "debtors": debtors, "blockers": [],
        "parameters": {"age_days": rules.age_days, "cross_age_bp": rules.cross_age_bp,
                       "concentration_bp": rules.concentration_bp, "advance_bp": rules.advance_bp},
        "invariants": {"net_equals_exclusions_plus_eligible": True, "base_within_commitment": True},
        "limitations": ["Synthetic US/USD receivables-only contract; not a funding authorization.",
                        "Concentration is applied at debtor level; no artificial invoice allocation."]}
