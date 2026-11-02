"""Small command surface: offline demo, review, export, and optional extraction."""

import argparse
import json
import os
from pathlib import Path
import sys

from .audit import AuditLog
from .extraction import approve_proposal, propose
from .packets import export_result, reconcile

ROOT = Path(__file__).resolve().parents[1]


def cases(root: Path = ROOT) -> list[dict]:
    path = root / "examples" / "cases.json"
    if not path.exists():
        raise ValueError("Run the demo from the cloned repository (examples directory is required)")
    return json.loads(path.read_text())


def case_path(case_id: str, root: Path = ROOT) -> Path:
    for case in cases(root):
        if case["id"] == case_id:
            return root / "examples" / case["packet"]
    raise ValueError("Unknown case identifier")


def evaluate(root: Path = ROOT) -> dict:
    results = []
    for case in cases(root):
        result = reconcile(root / "examples" / case["packet"])
        passed = all(result.get(k) == v for k, v in case["expected"].items())
        results.append({"id": case["id"], "name": case["name"], "passed": passed,
                        "expected": case["expected"], "actual": {k: result.get(k) for k in case["expected"]},
                        "blockers": result["blockers"]})
    return {"suite": "ten-synthetic-acceptance-cases", "passed": sum(r["passed"] for r in results),
            "total": len(results), "live_llm_evaluated": False, "results": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="BorrowCheck: evidence-linked receivables reconciliation")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("cases", help="List the ten synthetic scenarios")
    demo = sub.add_parser("demo", help="Run a bundled synthetic example without any API key")
    demo.add_argument("--case", default="04_worked")
    demo.add_argument("--out", type=Path, default=Path("outputs/demo"))
    run = sub.add_parser("run", help="Validate and reconcile a packet")
    run.add_argument("packet", type=Path)
    run.add_argument("--out", type=Path, default=Path("outputs/run"))
    evaluate_parser = sub.add_parser("evaluate", help="Run all ten acceptance cases")
    evaluate_parser.add_argument("--out", type=Path)
    serve = sub.add_parser("serve", help="Start the local-only review workspace")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--audit-db", type=Path, default=Path(".borrowcheck/audit.sqlite"))
    extract = sub.add_parser("extract", help="Produce unapproved candidate rules")
    extract.add_argument("packet", type=Path)
    extract.add_argument("--provider", choices=("local", "openrouter"), default="local")
    extract.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL", ""))
    extract.add_argument("--allow-network", action="store_true", help="Explicitly allow sending this packet's documents to OpenRouter")
    extract.add_argument("--out", type=Path, default=Path("outputs/proposal.json"))
    approve = sub.add_parser("approve-proposal", help="Record a local human review in a new packet file")
    approve.add_argument("packet", type=Path)
    approve.add_argument("proposal", type=Path)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--attest-reviewed", action="store_true")
    approve.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify-audit", help="Verify the local audit chain")
    verify.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "cases":
            for case in cases():
                print(f"{case['id']:22} {case['name']}")
        elif args.command in ("demo", "run"):
            path = case_path(args.case) if args.command == "demo" else args.packet
            result = reconcile(path)
            export_result(result, args.out)
            print(json.dumps({k: result.get(k) for k in ("run_id", "status", "base", "reported", "variance", "blockers")}, indent=2))
            print(f"Evidence exports: {args.out.resolve()}")
            return 2 if result["status"] == "BLOCKED" else 0
        elif args.command == "evaluate":
            result = evaluate()
            text = json.dumps(result, indent=2) + "\n"
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(text)
            print(text)
            return 0 if result["passed"] == result["total"] else 1
        elif args.command == "serve":
            from .web import serve
            serve(args.port, args.audit_db)
        elif args.command == "extract":
            if args.provider == "openrouter" and not args.allow_network:
                raise ValueError("Use --allow-network only after reviewing which public/synthetic documents will be sent")
            result = propose(args.packet.resolve(), args.provider, args.model, Path(".borrowcheck/proposals"))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=2) + "\n")
            print(f"{result['status']}: {args.out}. Extraction mode: {result['metadata']['provider']}")
        elif args.command == "approve-proposal":
            if not args.attest_reviewed:
                raise ValueError("Compare all proposed terms with the source, then use --attest-reviewed")
            approve_proposal(args.packet.resolve(), args.proposal, args.reviewer, args.out.resolve())
            print(f"Local demo review recorded in {args.out}; this does not authenticate a lender")
        elif args.command == "verify-audit":
            if not args.path.exists():
                raise ValueError("Audit database does not exist")
            events = AuditLog(args.path).events()
            print(f"Audit chain verified: {len(events)} events")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
