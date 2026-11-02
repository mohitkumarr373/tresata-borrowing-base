# Packet and output format

The runnable schema example is [the worked packet](../examples/04_worked/packet.json). All amounts in files and JSON results are decimal **strings**, never floating-point JSON numbers. Internally they become integer cents.

| Packet field | Contract |
|---|---|
| `schema_version`, `facility_id`, `currency` | Version 1, explicit facility and USD only |
| `as_of`, `knowledge_as_of` | Strict `YYYY-MM-DD`; report date and the knowledge cut-off used for rule selection |
| `documents` | IDs, relative files and SHA-256; paths must remain inside the packet folder |
| `ledger`, `ledger_sha256` | Relative CSV path and separate raw file SHA-256 |
| `control_totals` | Independently supplied gross amount and row count; recomputed on intake |
| `attestations` | Named reviewer confirms document completeness, legal eligibility and debtor identity |
| `rule_versions` | Facility, effective interval, recorded date, four parameters, supported mechanics, six evidence spans and reviewed-payload hash |
| `reserve` | Exact amount and quote, explicit confirmation, validity interval |
| `commitment` | Exact amount and source quote |
| `certificate` | Optional reported amount and exact quote; absent certificate means null variance |
| `synthetic` | True for every bundled packet |

CSV headers, in order:

```text
invoice_id,debtor_id,debtor_name,invoice_date,currency,amount,credit,disputed
```

Each record needs a unique invoice ID, a reviewed debtor ID, a non-future invoice date, USD, non-negative amounts with at most two decimals, allocated credits no greater than gross, and literal `true` or `false` for dispute status. Leading/trailing whitespace, thousands separators, scientific notation, NaN and excess decimal places are rejected. Credits are invoice allocations, not unallocated debtor credits.

The four parameters are `age_days`, `cross_age_bp`, `concentration_bp` and `advance_bp`. Supported mechanics explicitly fix `GT` ageing, `GTE` cross-ageing, net-before-eligibility cross-age denominator, post-eligibility/pre-concentration concentration denominator, full-invoice dispute exclusion and cent flooring. A different denominator is an unsupported contract, not an invitation to guess.

`READY_FOR_REVIEW` results contain monetary totals, signed variance, per-invoice reasons and provenance, debtor concentration calculations, rule/control evidence, source hashes, engine version and a content-derived run ID. The human review event is separate from this result. `BLOCKED` results contain null base/variance, reasons and replay identifiers; the CLI exits 2.

Evidence offsets are zero-based, end-exclusive **Unicode code points**. They are not byte offsets or JavaScript UTF-16 indices. Native PDF coordinates use Poppler's page coordinate system and reference the hash-bound original. TXT coordinates are line numbers and text offsets. CSV references distinguish logical records from physical lines.

JSON ingestion rejects duplicate keys and non-finite values. Document size is capped at 20 MiB, packet JSON at 5 MiB and ledger CSV at 100 MiB. No scanned-PDF OCR, XLSX parser, foreign currency conversion or arbitrary expression evaluator is supplied.

`python tools/generate_fixtures.py` recreates the synthetic corpus. It intentionally regenerates the bundled fixtures; expected financial outcomes are written explicitly, not produced by the calculator under test. Custom packets belong in a separate directory.
