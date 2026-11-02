"""Loopback-only prototype UI. No public deployment or production auth claims."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit

from .audit import AuditLog
from .cli import ROOT, case_path, cases, evaluate
from .evidence import contained, read_document
from .packets import read_json, reconcile, strict_json
from .report import html_report

STATIC = Path(__file__).parent / "static"


def make_server(port: int, audit_path: Path, root: Path = ROOT) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("Port must be in [0, 65535]")
    token = secrets.token_urlsafe(32)
    audit = AuditLog(audit_path)

    class Handler(BaseHTTPRequestHandler):
        server_version = "BorrowCheck/1.0"

        def log_message(self, fmt, *args):
            pass

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            raw = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body).encode())
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def authorized_host(self):
            port = self.server.server_port
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            return self.headers.get("Host") in allowed

        def do_GET(self):
            if not self.authorized_host():
                return self.send(403, {"error": "Loopback host required"})
            url = urlsplit(self.path)
            params = parse_qs(url.query)
            try:
                if url.path in ("/", "/app.js", "/style.css"):
                    name = "index.html" if url.path == "/" else url.path[1:]
                    content = {"index.html": "text/html", "app.js": "application/javascript", "style.css": "text/css"}[name]
                    return self.send(200, (STATIC / name).read_bytes(), content + "; charset=utf-8")
                if url.path == "/api/state":
                    return self.send(200, {"cases": cases(root), "csrf_token": token, "mode": "LOCAL_SYNTHETIC_DEMO"})
                if url.path == "/api/evaluate":
                    return self.send(200, evaluate(root))
                if url.path == "/api/audit":
                    return self.send(200, {"events": audit.events()[-100:], "identity_authenticated": False})
                case_id = params.get("case", ["04_worked"])[0]
                packet_path = case_path(case_id, root)
                if url.path == "/api/result":
                    return self.send(200, reconcile(packet_path))
                if url.path == "/api/report":
                    return self.send(200, html_report(reconcile(packet_path)), "text/html; charset=utf-8")
                if url.path == "/api/source":
                    spec_id = params.get("id", [""])[0]
                    packet = read_json(packet_path)
                    spec = next((s for s in packet["documents"] if s["id"] == spec_id), None)
                    if not spec:
                        raise ValueError("Unknown source document")
                    doc = read_document(contained(packet_path.parent, spec["file"]))
                    if doc["sha256"] != spec["sha256"]:
                        raise ValueError("Source changed; reconcile a newly reviewed packet")
                    return self.send(200, {"id": spec_id, "sha256": doc["sha256"], "text": doc["text"]})
                return self.send(404, {"error": "Not found"})
            except (ValueError, OSError, KeyError) as exc:
                return self.send(400, {"error": str(exc)})

        def do_POST(self):
            origin = self.headers.get("Origin")
            expected_origins = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if not self.authorized_host() or (origin is not None and origin not in expected_origins) or not secrets.compare_digest(self.headers.get("X-Review-Token", ""), token):
                return self.send(403, {"error": "Review token and same-origin request required"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("Expected a JSON body smaller than 16 KiB")
                payload = strict_json(self.rfile.read(length).decode())
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
                result = reconcile(case_path(payload.get("case", ""), root))
                if self.path == "/api/run":
                    event = audit.append("RECONCILIATION", {"run_id": result["run_id"], "status": result["status"]})
                    return self.send(200, {"result": result, "audit_digest": event})
                if self.path == "/api/signoff":
                    if payload.get("run_id") != result["run_id"]:
                        raise ValueError("Source packet changed; review a fresh reconciliation")
                    event = audit.signoff(result, payload.get("reviewer"), payload.get("note"))
                    return self.send(200, {"status": "LOCAL_DEMO_SIGNOFF", "audit_digest": event,
                                           "message": "Local review recorded. This is not an authenticated lender approval."})
                return self.send(404, {"error": "Not found"})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                return self.send(400, {"error": str(exc)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port: int, audit_path: Path):
    server = make_server(port, audit_path)
    print(f"BorrowCheck review workspace: http://127.0.0.1:{server.server_port}", flush=True)
    print("Local synthetic demonstration. Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
