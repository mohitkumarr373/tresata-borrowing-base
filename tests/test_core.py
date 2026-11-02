import copy
import csv
from dataclasses import replace
from datetime import date, timedelta
from fractions import Fraction
import io
import json
from pathlib import Path
import random
import shutil
import tempfile
import unittest

from borrowcheck.cli import ROOT, evaluate
from borrowcheck.engine import Invoice, Rules, calculate
from borrowcheck.evidence import canonical_hash, digest, read_document, span, validate_span
from borrowcheck.money import cents, floor_rate, money
from borrowcheck.packets import approve_rule, export_result, read_json, reconcile, strict_json

ASOF = date(2026, 10, 31)


class MoneyTests(unittest.TestCase):
    def test_exact_money_roundtrip(self):
        for text, expected in [("0", 0), ("0.01", 1), ("1.2", 120), ("123456789012345.67", 12345678901234567)]:
            self.assertEqual(cents(text), expected)
            self.assertEqual(cents(money(expected)), expected)

    def test_invalid_money_never_coerced(self):
        for value in [1.2, True, None, "NaN", "Infinity", "1e3", "-1", " 10", "10 ", "1.001", "1,000", ".5", "00"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                cents(value)

    def test_signed_variance(self):
        self.assertEqual(money(-101), "-1.01")

    def test_fractional_cent_floor(self):
        self.assertEqual(floor_rate(1, 8000), 0)
        self.assertEqual(floor_rate(101, 2000), 20)

    def test_rate_validation(self):
        for rate in [-1, 10001, True, .2]:
            with self.assertRaises(ValueError):
                floor_rate(100, rate)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.rules = Rules(90, 5000, 2000, 8000, 5000000, 100000000, "test")

    def invoice(self, id, debtor, amount, age=30, credit=0, disputed=False):
        return Invoice(id, debtor, debtor, ASOF - timedelta(days=age), amount, credit, disputed)

    def test_empty_ledger_is_zero_not_error(self):
        self.assertEqual(calculate([], self.rules, ASOF)["base"], "0.00")

    def test_duplicate_invoice_blocked(self):
        row = self.invoice("x", "a", 100)
        with self.assertRaises(ValueError):
            calculate([row, row], self.rules, ASOF)

    def test_future_invoice_blocked(self):
        with self.assertRaises(ValueError):
            calculate([self.invoice("x", "a", 100, age=-1)], self.rules, ASOF)

    def test_credit_over_allocation_blocked(self):
        with self.assertRaises(ValueError):
            calculate([self.invoice("x", "a", 100, credit=101)], self.rules, ASOF)

    def test_invalid_dispute_type_blocked(self):
        with self.assertRaises(ValueError):
            calculate([self.invoice("x", "a", 100, disputed="false")], self.rules, ASOF)

    def test_commitment_cap(self):
        result = calculate([self.invoice(str(i), str(i), 20000000) for i in range(5)], replace(self.rules, commitment=100), ASOF)
        self.assertEqual(result["base"], "1.00")

    def test_reserve_floor(self):
        result = calculate([self.invoice("1", "A", 100)], self.rules, ASOF)
        self.assertEqual(result["base"], "0.00")

    def test_zero_net_debtor_not_cross_aged(self):
        result = calculate([self.invoice("1", "A", 100, 100, credit=100)], self.rules, ASOF)
        self.assertFalse(result["debtors"][0]["cross_aged"])

    def test_permutation_invariance(self):
        rows = [self.invoice(str(i), str(i % 7), 10000 + i, age=i % 100) for i in range(80)]
        a = calculate(rows, self.rules, ASOF)
        random.Random(11).shuffle(rows)
        b = calculate(rows, self.rules, ASOF)
        for key in ["base", "eligible", "concentration_exclusions", "eligibility_exclusions"]:
            self.assertEqual(a[key], b[key])

    def test_randomized_against_independent_fraction_oracle(self):
        rng = random.Random(2023)
        for _ in range(120):
            rows = [self.invoice(str(i), str(rng.randrange(8)), rng.randrange(10000), rng.randrange(160), disputed=rng.random() < .1) for i in range(rng.randrange(1, 60))]
            rules = replace(self.rules, reserve=rng.randrange(1000), advance_bp=rng.randrange(1, 10001), concentration_bp=rng.randrange(1, 10001))
            eligible_balances = []
            for debtor in {r.debtor_id for r in rows}:
                group = [r for r in rows if r.debtor_id == debtor]
                net = sum(r.amount - r.credit for r in group)
                old = sum(r.amount - r.credit for r in group if (ASOF-r.invoice_date).days > 90)
                crossed = net > 0 and Fraction(old, net) >= Fraction(1, 2)
                eligible_balances.append(sum(r.amount-r.credit for r in group if not crossed and not r.disputed and (ASOF-r.invoice_date).days <= 90))
            pool = sum(eligible_balances)
            cap = int(Fraction(pool * rules.concentration_bp, 10000))
            eligible = sum(min(v, cap) for v in eligible_balances)
            expected = min(rules.commitment, max(0, int(Fraction(eligible * rules.advance_bp, 10000))-rules.reserve))
            actual = calculate(rows, rules, ASOF)
            self.assertEqual(actual["base"], money(expected))
            self.assertEqual(cents(actual["net"]), cents(actual["eligible"])+cents(actual["eligibility_exclusions"])+cents(actual["concentration_exclusions"]))


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "packet"
        shutil.copytree(ROOT / "examples/04_worked", self.root)
        self.path = self.root / "packet.json"
        self.packet = read_json(self.path)

    def write(self):
        self.path.write_text(json.dumps(self.packet))

    def blocked(self, substring):
        self.write()
        result = reconcile(self.path)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNone(result["base"])
        self.assertIn(substring, " ".join(result["blockers"]))

    def test_all_ten_acceptance_cases(self):
        report = evaluate()
        self.assertEqual(report["total"], 10)
        self.assertEqual(report["passed"], 10)
        self.assertFalse(report["live_llm_evaluated"])

    def test_original_case_and_evidence(self):
        result = reconcile(self.path)
        self.assertEqual(result["base"], "478000.00")
        self.assertEqual(result["variance"], "96000.00")
        self.assertEqual(len(result["rule_evidence"]), 6)
        self.assertEqual(result["invoices"][0]["source"]["record"], 1)

    def test_overlap_preserves_three_reasons(self):
        r = reconcile(ROOT / "examples/05_overlap/packet.json")
        self.assertEqual(r["invoices"][0]["reasons"], ["AGE", "DISPUTE", "CROSS_AGE"])
        self.assertEqual(r["eligibility_exclusions"], "200000.00")

    def test_exact_age_boundary(self):
        r = reconcile(ROOT / "examples/02_age_boundary/packet.json")
        self.assertEqual(r["invoices"][0]["reasons"], [])
        self.assertIn("AGE", r["invoices"][1]["reasons"])

    def test_cross_age_boundary(self):
        r = reconcile(ROOT / "examples/03_cross_age/packet.json")
        debtors = {d["debtor_id"]:d for d in r["debtors"]}
        self.assertFalse(debtors["A"]["cross_aged"])
        self.assertTrue(debtors["B"]["cross_aged"])

    def test_rule_tampering_invalidates_review(self):
        self.packet["rule_versions"][0]["parameters"]["advance_bp"] = 9999
        self.blocked("RULE_NOT_APPROVED")

    def test_source_tampering(self):
        with (self.root / "agreement.txt").open("a") as f:
            f.write("altered")
        self.blocked("SOURCE_HASH_MISMATCH")

    def test_fabricated_span_even_with_new_seal(self):
        rule = self.packet["rule_versions"][0]
        rule["evidence"]["age_days"]["quote"] = "An invented clause"
        approve_rule(rule, "Test review")
        self.blocked("does not reproduce")

    def test_conflicting_active_versions(self):
        self.packet["rule_versions"].append(copy.deepcopy(self.packet["rule_versions"][0]))
        self.blocked("RULE_VERSION_AMBIGUOUS")

    def test_expired_rule(self):
        self.packet["rule_versions"][0]["effective_to"] = "2026-10-30"
        self.blocked("RULE_VERSION_AMBIGUOUS")

    def test_future_knowledge_rule(self):
        self.packet["rule_versions"][0]["recorded_on"] = "2026-12-01"
        self.blocked("RULE_VERSION_AMBIGUOUS")

    def test_missing_legal_attestation(self):
        self.packet["attestations"]["legal_eligibility"] = False
        self.blocked("ATTESTATION_MISSING")

    def test_stale_reserve(self):
        self.packet["reserve"]["valid_to"] = "2026-10-30"
        self.blocked("RESERVE_STALE")

    def test_reserve_cannot_differ_from_quote(self):
        self.packet["reserve"]["amount"] = "0.00"
        self.blocked("CONTROL_EVIDENCE_MISMATCH")

    def test_commitment_cannot_differ_from_quote(self):
        self.packet["commitment"]["amount"] = "1.00"
        self.blocked("CONTROL_EVIDENCE_MISMATCH")

    def test_wrong_control_total(self):
        self.packet["control_totals"]["gross"] = "1.00"
        self.blocked("CONTROL_TOTAL_MISMATCH")

    def test_ledger_tampering(self):
        (self.root / "ledger.csv").write_text((self.root / "ledger.csv").read_text().replace("100000.00", "999999.00", 1))
        self.blocked("LEDGER_HASH_MISMATCH")

    def test_document_path_traversal(self):
        self.packet["documents"][0]["file"] = "../../outside.txt"
        self.blocked("outside")

    def test_unsupported_mechanics(self):
        rule = self.packet["rule_versions"][0]
        rule["mechanics"]["concentration_denominator"] = "POST_CONCENTRATION"
        approve_rule(rule, "Test review")
        self.blocked("UNSUPPORTED_RULE")

    def test_false_source_coordinates_blocked(self):
        rule = self.packet['rule_versions'][0]
        rule['evidence']['age_days']['start_line'] = 999
        approve_rule(rule, 'Test review')
        self.blocked('coordinates differ')

    def test_malformed_nested_objects_fail_closed(self):
        original = copy.deepcopy(self.packet)
        for key in ['attestations', 'reserve', 'documents', 'rule_versions']:
            with self.subTest(key=key):
                self.packet = copy.deepcopy(original)
                self.packet[key] = 123
                self.write()
                self.assertEqual(reconcile(self.path)['status'], 'BLOCKED')

    def test_boolean_schema_version_rejected(self):
        self.packet['schema_version'] = True
        self.blocked('Unsupported packet schema')

    def test_deterministic_replay(self):
        self.assertEqual(reconcile(self.path), reconcile(self.path))

    def test_amendment_asof_selection(self):
        source = ROOT / "examples/08_amendment"
        shutil.rmtree(self.root)
        shutil.copytree(source, self.root)
        self.packet = read_json(self.path)
        self.assertEqual(reconcile(self.path)["base"], "510000.00")
        self.packet["as_of"] = "2026-10-31"; self.write()
        self.assertEqual(reconcile(self.path)["base"], "478000.00")

    def test_exports_escape_html_and_csv_formula(self):
        result = reconcile(self.path)
        result["invoices"][0]["debtor_name"] = "=SUM(A1)"
        result["rule_evidence"]["age_days"]["quote"] = '<script>alert(1)</script>'
        dest = Path(self.tmp.name) / "export"
        export_result(result, dest)
        self.assertIn("'=SUM(A1)", (dest / "invoices.csv").read_text())
        self.assertNotIn("<script>", (dest / "evidence.html").read_text())
        self.assertIn("&lt;script&gt;", (dest / "evidence.html").read_text())


class EvidenceTests(unittest.TestCase):
    def test_unicode_offsets_and_line_refs(self):
        text = "α 😀\nExact clause.\n"
        doc = {"text": text, "sha256":digest(text.encode()), "text_sha256":digest(text.encode())}
        ref = span("x", doc, "Exact clause.")
        self.assertEqual(ref["start_line"], 2)
        self.assertEqual(ref["start"], 4)
        validate_span(ref, {"x":doc})

    def test_ambiguous_quote_rejected(self):
        with self.assertRaises(ValueError):
            span("x", {"text":"same same"}, "same")

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError):
            strict_json('{"amount":1,"amount":2}')

    def test_nonfinite_json_rejected(self):
        with self.assertRaises(ValueError):
            strict_json('{"amount":NaN}')


if __name__ == "__main__":
    unittest.main()
