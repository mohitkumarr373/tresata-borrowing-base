# Security and operational boundary

BorrowCheck is a local demonstration using public/synthetic inputs. It is not a production lending system or a financial/legal advice service.

The review server binds only to `127.0.0.1`. It validates the Host header, uses a per-process token and same-origin checks for POST requests, limits request sizes, escapes displayed evidence, restricts source paths, sets a content security policy and prevents common CSV formula injection. Do not proxy it onto the public internet. Python's [http.server documentation](https://docs.python.org/3.12/library/http.server.html) explicitly limits its production suitability.

The optional model adapter requires an API key, an explicit model and `--allow-network`. That flag permits the selected source texts to be sent to OpenRouter and its routed provider. Provider retention/training terms are not enforced by this prototype. Use synthetic/public inputs; real borrower documents require approved contractual and technical controls. API keys are excluded from saved model metadata, and `.env`, caches, outputs and local databases are git-ignored.

Source documents are untrusted data. A small phrase detector quarantines the seeded hostile example; it cannot detect all prompt injection. The stronger boundary is that a model only emits a proposal, generated code is never executed, and model responses cannot authorize funds. A real quote with a wrong numeric interpretation can still pass structural validation; human semantic review is mandatory.

The JSON review hash and SQLite hash chain detect some accidental alterations. They are not signatures, immutable storage, identity authentication or non-repudiation. Anyone controlling local files can rewrite hashes, approval metadata or the entire chain, and deletion of a final event needs an external anchor to detect. A missing amendment, incorrect human attestation or internally consistent fabricated ledger can escape all implemented checks.

Before real use I would require authenticated maker/checker separation, least-privilege access, tenant isolation, encryption and retention controls, signed versioned approvals, externally anchored logs, sandboxed and patched document extraction, independently validated rules/models, incident response and counsel/credit-officer ownership. The prototype's final review is not a substitute for these controls.
