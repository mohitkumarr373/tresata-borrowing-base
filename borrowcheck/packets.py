"""Validate evidence and approval gates before reaching the pure calculator."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from pathlib import Path

from . import __version__
from .engine import Invoice, Rules, calculate
from .evidence import canonical_hash, contained, digest, read_document, suspect_instructions, validate_span
from .money import cents, money

PARAMETERS = {"age_days", "cross_age_bp", "concentration_bp", "advance_bp"}
MECHANICS = {"age_comparison": "GT", "cross_age_comparison": "GTE",
             "cross_age_denominator": "NET_BEFORE_ELIGIBILITY",
             "concentration_denominator": "POST_ELIGIBILITY_PRE_CONCENTRATION",
             "rounding": "FLOOR_CENTS", "dispute_policy": "EXCLUDE_FULL_INVOICE"}
HEADERS = ["invoice_id", "debtor_id", "debtor_name", "invoice_date", "currency", "amount", "credit", "disputed"]


def strict_date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected an ISO date YYYY-MM-DD")
    return date.fromisoformat(value)


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError(f"Duplicate JSON key: {k}")
        result[k] = v
    return result


def strict_json(text: str):
    def bad_constant(value):
        raise ValueError(f"Invalid JSON number: {value}")
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=bad_constant)


def read_json(path: Path) -> dict:
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("Packet configuration exceeds 5 MiB")
    data = strict_json(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def rule_payload(rule: dict) -> dict:
    return {key: value for key, value in rule.items() if key != "approval"}


def approve_rule(rule: dict, reviewer: str, *, kind: str = "LOCAL_DEMO") -> dict:
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120:
        raise ValueError("A reviewer name is required (maximum 120 characters)")
    rule["approval"] = {"reviewer": reviewer.strip(), "kind": kind,
                        "payload_sha256": canonical_hash(rule_payload(rule))}
    return rule


def documents_for(packet_path: Path, packet: dict) -> dict:
    documents = {}
    if not isinstance(packet["documents"], list):
        raise ValueError("Document manifest must be a list")
    for spec in packet["documents"]:
        if not isinstance(spec, dict) or not isinstance(spec.get("id"), str) or not spec["id"] or spec["id"] in documents:
            raise ValueError("Invalid or duplicate document identifier")
        path = contained(packet_path.parent, spec["file"])
        doc = read_document(path)
        if doc["sha256"] != spec["sha256"]:
            raise ValueError(f"SOURCE_HASH_MISMATCH: {spec['id']}")
        doc["file"] = spec["file"]
        if suspect_instructions(doc["text"]):
            raise ValueError(f"SOURCE_QUARANTINED: suspicious instruction in {spec['id']}; manual source review required")
        documents[spec["id"]] = doc
    if not documents:
        raise ValueError("Document manifest is empty")
    return documents


def active_rule(packet: dict, documents: dict) -> dict:
    as_of = strict_date(packet["as_of"])
    knowledge = strict_date(packet["knowledge_as_of"])
    if knowledge < as_of:
        raise ValueError("Knowledge cutoff cannot precede the reporting date")
    active = []
    if not isinstance(packet["rule_versions"], list):
        raise ValueError("Rule versions must be a list")
    for rule in packet["rule_versions"]:
        if not isinstance(rule, dict):
            raise ValueError("Each rule version must be an object")
        start = strict_date(rule["effective_from"])
        end = strict_date(rule["effective_to"]) if rule.get("effective_to") else date.max
        recorded = strict_date(rule["recorded_on"])
        if end < start:
            raise ValueError("Rule effective interval is reversed")
        if start <= as_of <= end and recorded <= knowledge:
            active.append(rule)
    if len(active) != 1:
        raise ValueError("RULE_VERSION_AMBIGUOUS: exactly one approved rule version must be active")
    rule = active[0]
    if rule.get("facility_id") != packet["facility_id"]:
        raise ValueError("Rule belongs to a different facility")
    approval = rule.get("approval", {})
    if not isinstance(approval, dict) or not isinstance(approval.get("reviewer"), str) or not approval["reviewer"].strip() or approval.get("payload_sha256") != canonical_hash(rule_payload(rule)):
        raise ValueError("RULE_NOT_APPROVED: missing or invalid review seal")
    if set(rule["parameters"]) != PARAMETERS or rule.get("mechanics") != MECHANICS:
        raise ValueError("UNSUPPORTED_RULE: unsupported parameters, denominator, or operation order")
    if set(rule.get("evidence", {})) != PARAMETERS | {"mechanics", "scope"}:
        raise ValueError("Rule evidence coverage is incomplete")
    for reference in rule["evidence"].values():
        validate_span(reference, documents)
    return rule


def load_invoices(root: Path, packet: dict) -> tuple[list[Invoice], str]:
    ledger_path = contained(root, packet["ledger"])
    if ledger_path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("Ledger exceeds the 100 MiB prototype limit")
    raw = ledger_path.read_bytes()
    if len(raw) > 100 * 1024 * 1024:
        raise ValueError("Ledger exceeds the 100 MiB prototype limit")
    ledger_hash = digest(raw)
    if packet.get("ledger_sha256") != ledger_hash:
        raise ValueError("LEDGER_HASH_MISMATCH")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    if reader.fieldnames != HEADERS:
        raise ValueError("Ledger columns do not match the documented schema")
    invoices = []
    for row_no, row in enumerate(reader, 1):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed CSV record {row_no}")
        if row["currency"] != "USD":
            raise ValueError(f"UNSUPPORTED_CURRENCY: record {row_no}")
        if row["disputed"] not in ("true", "false"):
            raise ValueError(f"Invalid disputed flag in record {row_no}")
        for key in ("invoice_id", "debtor_id", "debtor_name"):
            if len(row[key]) > 200 or row[key] != row[key].strip():
                raise ValueError(f"Invalid {key} in record {row_no}")
        invoices.append(Invoice(row["invoice_id"], row["debtor_id"], row["debtor_name"],
                                strict_date(row["invoice_date"]), cents(row["amount"]),
                                cents(row["credit"]), row["disputed"] == "true",
                                {"file": packet["ledger"], "sha256": ledger_hash,
                                 "record": row_no, "physical_end_line": reader.line_num,
                                 "columns": HEADERS}))
    if type(packet["control_totals"]["invoice_count"]) is not int or packet["control_totals"]["invoice_count"] != len(invoices):
        raise ValueError("CONTROL_TOTAL_MISMATCH: invoice count")
    if cents(packet["control_totals"]["gross"]) != sum(i.amount for i in invoices):
        raise ValueError("CONTROL_TOTAL_MISMATCH: gross receivables")
    return invoices, ledger_hash


def cited_amount(control: dict, documents: dict, field: str = "amount") -> int:
    validate_span(control["evidence"], documents)
    amount = cents(control[field])
    quoted = re.findall(r"\bUSD\s+([0-9]+\.[0-9]{2})\b", control["evidence"]["quote"])
    if len(quoted) != 1 or cents(quoted[0]) != amount:
        raise ValueError("CONTROL_EVIDENCE_MISMATCH: amount does not equal its unique cited USD value")
    return amount


def reconcile(packet_path: str | Path) -> dict:
    path = Path(packet_path).resolve()
    packet_hash = None
    try:
        packet = read_json(path)
        packet_hash = canonical_hash(packet)
        if type(packet.get("schema_version")) is not int or packet["schema_version"] != 1 or packet.get("currency") != "USD":
            raise ValueError("Unsupported packet schema or currency")
        if not isinstance(packet.get("facility_id"), str) or not packet["facility_id"]:
            raise ValueError("Missing facility identity")
        attest = packet.get("attestations", {})
        if not isinstance(attest, dict) or any(attest.get(k) is not True for k in ("manifest_complete", "legal_eligibility", "debtor_identity")):
            raise ValueError("ATTESTATION_MISSING: document completeness, legal eligibility, and debtor identity are required")
        if not isinstance(attest.get("reviewer"), str) or not attest["reviewer"].strip():
            raise ValueError("Attestation reviewer is missing")
        documents = documents_for(path, packet)
        rule = active_rule(packet, documents)
        as_of = strict_date(packet["as_of"])
        reserve = packet["reserve"]
        if not isinstance(reserve, dict) or reserve.get("confirmed") is not True:
            raise ValueError("RESERVE_UNCONFIRMED: missing reserve is not zero")
        if not strict_date(reserve["valid_from"]) <= as_of <= strict_date(reserve["valid_to"]):
            raise ValueError("RESERVE_STALE: reserve confirmation does not cover reporting date")
        reserve_amount = cited_amount(reserve, documents)
        commitment = packet["commitment"]
        commitment_amount = cited_amount(commitment, documents)
        reported = None
        if packet.get("certificate") is not None:
            reported = cited_amount(packet["certificate"], documents, "reported")
        invoices, ledger_hash = load_invoices(path.parent, packet)
        rules = Rules(**rule["parameters"], reserve=reserve_amount,
                      commitment=commitment_amount, rule_id=rule["id"])
        result = calculate(invoices, rules, as_of, reported)
        result.update({"facility_id": packet["facility_id"], "name": packet.get("name", packet["facility_id"]),
                       "knowledge_as_of": packet["knowledge_as_of"], "approval": rule["approval"],
                       "rule_evidence": rule["evidence"], "reserve_evidence": reserve["evidence"],
                       "commitment_evidence": commitment["evidence"],
                       "certificate_evidence": packet.get("certificate", {}).get("evidence") if packet.get("certificate") else None,
                       "documents": [{"id": k, "sha256": d["sha256"], "text_sha256": d["text_sha256"], "file": d["file"]}
                                     for k, d in documents.items()], "ledger_sha256": ledger_hash,
                       "packet_sha256": packet_hash, "engine_version": __version__,
                       "synthetic": packet.get("synthetic") is True})
    except (ValueError, KeyError, TypeError, OSError, UnicodeError) as exc:
        result = {"status": "BLOCKED", "base": None, "variance": None,
                  "blockers": [str(exc)], "invoices": [], "debtors": [],
                  "packet_sha256": packet_hash, "engine_version": __version__}
    result["run_id"] = canonical_hash(result)[:24]
    return result


def export_result(result: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "reconciliation.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    fields = ["invoice_id", "debtor_id", "debtor_name", "age_days", "gross", "credit", "net",
              "excluded", "pre_concentration_eligible", "reasons"]
    with (output / "invoices.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in result.get("invoices", []):
            safe = {k: row[k] for k in fields}
            safe["reasons"] = ";".join(safe["reasons"])
            for k in ("invoice_id", "debtor_id", "debtor_name"):
                if safe[k].lstrip().startswith(("=", "+", "-", "@")):
                    safe[k] = "'" + safe[k]
            writer.writerow(safe)
    from .report import html_report
    (output / "evidence.html").write_text(html_report(result), encoding="utf-8")
