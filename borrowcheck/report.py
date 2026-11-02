"""Self-contained, escaped HTML exports; safe to inspect without a server."""

from html import escape


def html_report(result: dict) -> str:
    esc = lambda value: escape(str(value))
    rows = "".join("<tr>" + "".join(f"<td>{esc(row.get(k, ''))}</td>" for k in
                   ("invoice_id", "debtor_id", "net", "excluded", "pre_concentration_eligible", "reasons")) + "</tr>"
                   for row in result.get("invoices", []))
    refs = dict(result.get("rule_evidence", {}))
    for key in ("reserve_evidence", "commitment_evidence", "certificate_evidence"):
        if result.get(key):
            refs[key] = result[key]
    evidence = "".join(f"<section><h3>{esc(key)}</h3><p>{esc(ref['document_id'])} / {esc(ref.get('clause',''))} / "
                       f"lines {esc(ref['start_line'])}-{esc(ref['end_line'])} / offsets {esc(ref['start'])}:{esc(ref['end'])}</p>"
                       f"<blockquote>{esc(ref['quote'])}</blockquote><small>SHA-256: {esc(ref['document_sha256'])}</small></section>"
                       for key, ref in refs.items())
    blockers = "".join(f"<li>{esc(b)}</li>" for b in result.get("blockers", []))
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>BorrowCheck evidence report</title><style>body{{font:15px/1.6 system-ui;max-width:1000px;margin:48px auto;padding:0 24px;color:#17324d}}h1{{font-size:32px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:9px;border-bottom:1px solid #dce4eb;text-align:left}}th{{background:#edf4f7}}section{{margin:24px 0;padding:18px;background:#f5f8fa;break-inside:avoid}}blockquote{{margin:12px 0;white-space:pre-wrap}}small{{overflow-wrap:anywhere}}.tag{{color:#087e8b;font-weight:700}}</style>
<h1>BorrowCheck / Evidence report</h1><p class="tag">{esc(result['status'])} · Synthetic demonstration · Not a funding instruction</p>
<p>Run {esc(result['run_id'])} · Engine {esc(result.get('engine_version',''))}</p>
<h2>Computed borrowing base: {esc(result.get('base') or 'WITHHELD')}</h2><p>Reported: {esc(result.get('reported'))} · Variance: {esc(result.get('variance'))}</p>
<ul>{blockers}</ul><table><thead><tr><th>Invoice</th><th>Debtor</th><th>Net</th><th>Excluded</th><th>Before cap</th><th>Reasons</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Source evidence</h2>{evidence}<p>Invoice coordinates and full calculation steps are in the accompanying reconciliation.json. Local review records do not authenticate a qualified lender.</p></html>"""
