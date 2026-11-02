# Architecture and financial contract

I use AI only where variable language creates interpretation work. A rules engine is sufficient after the terms and identities have been reviewed. This prototype deliberately makes that boundary visible.

## Implemented pipeline

1. **Intake:** Load a facility packet, document manifest, invoice CSV and control totals. Check file containment, size limits, hashes, supported currency, strict decimal strings, dates, invoice uniqueness and required attestations. Preserve document originals.
2. **Optional proposal:** Retrieve paragraphs using BM25 plus TF-IDF cosine similarity; expand numbered section references transitively. For small inputs, give the LLM the full document texts as well as retrieved passages. Refuse context above 48,000 characters instead of silently dropping clauses. This is lexical/statistical retrieval, not a pretrained semantic embedding service.
3. **Review:** Validate a four-parameter JSON schema, exact contiguous quotes, and unsupported-condition declarations. One LLM validation repair is allowed. A human compares the proposal with the complete contract and writes a new reviewed packet. Merely extracting a quote does not make its numeric interpretation correct.
4. **Version selection:** Select exactly one rule version active on the reporting date and recorded by `knowledge_as_of`. Check the reviewed payload hash and six required evidence references. Unsupported mechanics, expired rules or conflicting versions block the result.
5. **Calculation:** Run the pure calculator over typed invoices and reviewed terms. It never calls a model, executes generated code, retrieves rules from the internet, or writes financial instructions.
6. **Release for review:** Export amounts, reasons, debtor caps, evidence and a deterministic run ID. Blocked packets produce no final amount. A local signoff event records a reviewer, rationale and result hash; it does not change the reconciliation to lender-approved status.

The model route sends source text to OpenRouter only after an explicit CLI flag. Its endpoint and wire format follow [OpenRouter's API documentation](https://openrouter.ai/docs/api/reference/overview) and [structured output documentation](https://openrouter.ai/docs/guides/features/structured-outputs). Each request names a model; temperature is zero, output is capped, and providers must support the requested parameters. These settings improve repeatability but do not prove correctness.

## Exact synthetic mechanics

All balances below are **integer cents**. A rate of 2,000 basis points means 20%. Let invoice `i` have gross `g_i`, allocated credit `c_i`, debtor `d(i)` and report-date age `a_i`:

- `net_i = g_i − c_i`, with `0 ≤ c_i ≤ g_i`.
- Debtor net `N_d = Σ net_i`; overdue `O_d = Σ net_i` where `a_i > 90`.
- Cross-age debtor `d` when `N_d > 0` and `O_d × 10000 ≥ N_d × 5000`. This denominator is computed **before eligibility exclusions**.
- Exclude an invoice if old, disputed, or its debtor is cross-aged. Keep all reasons, remove its net amount once.
- `E_d` is the debtor's remaining balance; `S = Σ E_d`.
- Per-debtor cap `C = floor(S × 2000 / 10000)`; eligible `E = Σ min(E_d, C)`. The denominator is fixed **before concentration**; no iterative recapping.
- `advance = floor(E × 8000 / 10000)`.
- `base = min(commitment, max(0, advance − reserve))`.
- `variance = reported − base`, so a positive value is a reported overstatement.

Floor each concentration cap and the aggregate advance to cents. Rounding each invoice's advance instead would define a different contract. All applicable rates are versioned. The amendment fixture changes only concentration to 2,500 bp from 1 November.

The engine checks `net = eligibility exclusions + concentration exclusions + eligible`. Concentration is a debtor-level deduction: I do not invent invoice-level allocations that the contract never specifies.

### Worked reconciliation

| Step | Amount |
|---|---:|
| Gross and net receivables | $1,000,000.00 |
| A: overdue $100,000 + current $100,000, both cross-aged | −$200,000.00 |
| Pre-concentration pool | $800,000.00 |
| B: $300,000 less its $160,000 cap | −$140,000.00 |
| Eligible receivables | $660,000.00 |
| 80% advance | $528,000.00 |
| Confirmed reserve | −$50,000.00 |
| Computed borrowing base | **$478,000.00** |
| Certificate | $574,000.00 |
| Reported overstatement | **$96,000.00** |

Omitting A's current invoice from exclusions adds $100,000 to eligibility and raises B's allowance by $20,000. Advancing 80% of that $120,000 difference explains the $96,000 variance.

## Evidence and knowledge maintenance

The source of truth is the reviewed source packet, not the retrieval index. Each rule reference stores document ID, SHA-256 of the raw file and normalized text, exact quote, clause, Unicode code-point start/end offsets and line numbers. Native PDF extraction additionally captures page and word bounding boxes. The CSV provenance stores the hashed file, logical record, physical end line and column names; quoted multiline records remain distinguishable.

A reviewer can start from the final base, inspect the advance/reserve/commitment, drill into debtor concentration and invoice reasons, then open the exact source span for each term. Changing source bytes invalidates the manifest; changing a rule invalidates its review seal. A deterministic run ID binds the resulting calculation and provenance. SHA-256 verifies content identity; it does not prove document authenticity or who approved it.

Rules include both effective time and recorded time. New amendments need a reviewed version, revised interval, refreshed evidence and regression cases. An amendment discovered late requires rerunning affected reports; it does not erase their original history. The prototype supports replay and rejects invalid versions; it does **not** implement automatic notice discovery, legal semantic diffs, impact scheduling or approval revocation services.

## Production extension and trade-offs

| Decision | Reason and cost |
|---|---|
| Integer cents and basis points | Exact, efficient and inspectable for this two-decimal, USD-only contract. FX and other rounding conventions need a new tested schema. |
| O(n + d) aggregation | Two invoice passes and debtor aggregation avoid repeated scans. Output retains O(n + d) evidence; large exports still need pagination/streaming in production. |
| No LLM per invoice | Stable rule reuse removes repeated token cost, latency and inconsistent interpretation. Human review remains a cost. |
| Full small-document context | Reduces retrieval omission risk at prototype scale. The explicit context limit blocks larger agreements. |
| Allowlisted mechanics | Easier to verify than a general expression language. Genuine exceptions require manual handling or a reviewed schema extension. |
| Local SQLite and JSON | Easy reproducibility, no cloud setup. They provide neither immutable storage nor authenticated approvals. |
| Human-approved debtor IDs | Avoids silent alias merges. Entity-resolution proposals can be added, but legal identity still needs review. |

I rejected an end-to-end calculating LLM, a generic RAG chatbot, and multiple debating agents: none establishes exact arithmetic, complete authority or lender approval. A facility-specific spreadsheet remains a serious baseline. If AI does not reduce interpretation and maintenance cost against it, I would remove the model layer.

Production requires authenticated maker/checker roles, tenant-isolated immutable object storage, versioned SQL rule records, signed approvals, an external audit anchor, verified OCR, model/provider governance, monitoring and incident handling. Local counsel must validate jurisdiction-specific assignment, security interests, enforcement and confidentiality. These are extension requirements, not implemented features or claims of compliance.
