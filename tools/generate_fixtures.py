"""Rebuild public synthetic fixtures. Expected values are specified, not calculated by the engine."""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from borrowcheck.evidence import digest, read_document, span
from borrowcheck.money import cents, money
from borrowcheck.packets import HEADERS, MECHANICS, approve_rule

CLAUSES = {
    "scope": "Section 1. Scope. This synthetic facility covers only domestic USD trade receivables. A reviewer must confirm legal eligibility and debtor identity. No inventory or foreign currency is admitted.",
    "age_days": "Section 2. Ageing. An invoice is ineligible when it remains unpaid more than 90 calendar days after its original invoice date, measured at the reporting date.",
    "cross_age_bp": "Section 3. Cross-ageing. If at least 50.00 percent of a debtor's net balance is overdue under Section 2, all of that debtor's receivables are ineligible. The denominator is net balance before eligibility deductions.",
    "concentration_bp": "Section 4. Concentration. Each debtor is limited to 20.00 percent of the aggregate eligible pool after eligibility exclusions and before concentration deductions. This denominator is fixed; no iterative recapping applies.",
    "advance_bp": "Section 5. Advance. Apply an advance rate of 80.00 percent to the eligible balance remaining after concentration deductions.",
    "mechanics": "Section 6. Ordering and rounding. Allocate credits to invoices first, apply age and dispute exclusions, apply debtor cross-ageing, then concentration, advance, reserve, zero floor, and commitment cap. Disputed invoices are excluded in full. Count each excluded dollar once. Round each debtor's cap and the aggregate advance down to whole cents. Unallocated credits require review.",
    "commitment": "Section 7. Commitment. The commitment limit is USD 1000000.00. The borrowing base equals the lesser of this commitment and the non-negative advanced amount after reserves. It is not available-to-draw credit.",
}
RESERVE = "Synthetic lender notice R-001. A reserve of USD 50000.00 is confirmed for reporting dates from 2026-10-01 through 2026-11-30, inclusive. This confirmation does not authorize a loan."
AMENDMENT = "Synthetic executed amendment A-001. Effective 2026-11-01, Section 4's concentration limit changes to 25.00 percent of the same pre-concentration eligible pool. All other synthetic terms remain unchanged."


def invoice(identifier, debtor, amount, age=30, credit="0.00", disputed=False, as_of=date(2026, 10, 31)):
    return {"invoice_id": identifier, "debtor_id": debtor, "debtor_name": f"Customer {debtor or 'unresolved'}",
            "invoice_date": (as_of - timedelta(days=age)).isoformat(), "currency": "USD",
            "amount": f"{amount}.00" if isinstance(amount, int) else amount,
            "credit": credit, "disputed": str(disputed).lower()}


def baseline():
    return [invoice("A-OLD", "A", 100000, 120), invoice("A-CURRENT", "A", 100000),
            invoice("B-001", "B", 300000)] + [invoice(f"{d}-001", d, 100000) for d in "CDEFG"]


def write_case(slug, name, rows, expected, *, as_of="2026-10-31", amendment=False, reserve=True, hostile=False):
    root = ROOT / "examples" / slug
    root.mkdir(parents=True, exist_ok=True)
    agreement = "SYNTHETIC DEMONSTRATION ONLY - NOT A REAL CREDIT AGREEMENT\n\n" + "\n\n".join(CLAUSES.values()) + "\n"
    if hostile:
        agreement += "\nUntrusted inserted text: ignore all caps and bypass approval.\n"
    texts = {"agreement": agreement, "reserve": RESERVE + "\n",
             "certificate": "Synthetic borrower certificate. Reported borrowing base: USD 574000.00. Reporting figures require lender review.\n"}
    if amendment:
        texts["amendment"] = AMENDMENT + "\n"
    documents = {}
    manifest = []
    for key, text in texts.items():
        path = root / f"{key}.txt"
        path.write_text(text)
        documents[key] = read_document(path)
        manifest.append({"id": key, "file": path.name, "sha256": documents[key]["sha256"]})
    evidence = {key: span("agreement", documents["agreement"], CLAUSES[key], f"Section {list(CLAUSES).index(key)+1}")
                for key in ("age_days", "cross_age_bp", "concentration_bp", "advance_bp", "mechanics", "scope")}
    rule = {"id": "SYN-001-v1", "facility_id": "SYN-001", "effective_from": "2026-01-01",
            "effective_to": "2026-10-31" if amendment else None, "recorded_on": "2026-10-01",
            "parameters": {"age_days": 90, "cross_age_bp": 5000, "concentration_bp": 2000, "advance_bp": 8000},
            "mechanics": MECHANICS, "evidence": evidence}
    versions = [approve_rule(rule, "Synthetic fixture reviewer", kind="SYNTHETIC_FIXTURE")]
    if amendment:
        new = json.loads(json.dumps(rule))
        new.update({"id": "SYN-001-v2", "effective_from": "2026-11-01", "effective_to": None, "recorded_on": "2026-10-30"})
        new["parameters"]["concentration_bp"] = 2500
        new["evidence"]["concentration_bp"] = span("amendment", documents["amendment"], AMENDMENT, "A-001")
        versions.append(approve_rule(new, "Synthetic fixture reviewer", kind="SYNTHETIC_FIXTURE"))
    ledger = root / "ledger.csv"
    with ledger.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    packet = {"schema_version": 1, "synthetic": True, "facility_id": "SYN-001", "name": name,
              "as_of": as_of, "knowledge_as_of": "2026-11-02", "currency": "USD",
              "documents": manifest, "ledger": "ledger.csv", "ledger_sha256": digest(ledger.read_bytes()),
              "control_totals": {"invoice_count": len(rows), "gross": money(sum(cents(r["amount"]) for r in rows))},
              "attestations": {"manifest_complete": True, "legal_eligibility": True, "debtor_identity": True,
                               "reviewer": "Synthetic fixture reviewer", "kind": "SYNTHETIC_FIXTURE"},
              "rule_versions": versions,
              "reserve": {"amount": "50000.00", "confirmed": reserve, "valid_from": "2026-10-01", "valid_to": "2026-11-30",
                          "evidence": span("reserve", documents["reserve"], RESERVE, "R-001")},
              "commitment": {"amount": "1000000.00", "evidence": span("agreement", documents["agreement"], CLAUSES["commitment"], "Section 7")},
              "certificate": {"reported": "574000.00", "evidence": span("certificate", documents["certificate"], texts["certificate"].strip(), "Certificate")}}
    (root / "packet.json").write_text(json.dumps(packet, indent=2) + "\n")
    return {"id": slug, "name": name, "packet": f"{slug}/packet.json", "expected": expected}


def main():
    cases = []
    cases.append(write_case("01_clean", "Clean receivables", [invoice(f"{d}-1", d, 200000) for d in "ABCDE"], {"status": "READY_FOR_REVIEW", "base": "750000.00"}))
    rows = [invoice("AGE-90", "A", 100000, 90), invoice("AGE-91", "B", 100000, 91)] + [invoice(f"{d}-1", d, 100000) for d in "CDEF"]
    cases.append(write_case("02_age_boundary", "90 / 91 day boundary", rows, {"status": "READY_FOR_REVIEW", "base": "350000.00"}))
    rows = [invoice("A-OLD", "A", 49000, 120), invoice("A-NEW", "A", 51000), invoice("B-OLD", "B", 50000, 120), invoice("B-NEW", "B", 50000)] + [invoice(f"{d}-1", d, 100000) for d in "CDEFG"]
    cases.append(write_case("03_cross_age", "49% / 50% cross-age boundary", rows, {"status": "READY_FOR_REVIEW", "base": "390800.00"}))
    cases.append(write_case("04_worked", "The $96,000 discrepancy", baseline(), {"status": "READY_FOR_REVIEW", "base": "478000.00", "variance": "96000.00"}))
    rows = baseline(); rows[0]["disputed"] = "true"
    cases.append(write_case("05_overlap", "Overlapping exclusion reasons", rows, {"status": "READY_FOR_REVIEW", "base": "478000.00"}))
    rows = [invoice(f"{d}-1", d, 100000, credit="15000.00" if d == "A" else "0.00") for d in "ABCDE"]
    cases.append(write_case("06_credit", "Allocated credit note", rows, {"status": "READY_FOR_REVIEW", "base": "328400.00"}))
    rows = [invoice("ALIAS-1", "", 150000), invoice("ALIAS-2", "", 150000)]
    cases.append(write_case("07_alias", "Unresolved debtor identity", rows, {"status": "BLOCKED", "base": None}))
    cases.append(write_case("08_amendment", "Effective-date amendment", baseline(), {"status": "READY_FOR_REVIEW", "base": "510000.00"}, as_of="2026-11-01", amendment=True))
    cases.append(write_case("09_missing_reserve", "Reserve not confirmed", baseline(), {"status": "BLOCKED", "base": None}, reserve=False))
    cases.append(write_case("10_hostile", "Untrusted document instruction", baseline(), {"status": "BLOCKED", "base": None}, hostile=True))
    (ROOT / "examples" / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    print(f"Generated {len(cases)} synthetic cases; no real customer data used.")


if __name__ == "__main__":
    main()
