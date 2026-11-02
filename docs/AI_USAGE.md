# Appendix — What I Added Beyond the AI

**Mohit Kumar · Entry No. 2023EE10862 · Tresata Assignment**

## 1. Where AI Helped

I used AI for problem selection, public-source exploration, architecture, synthetic financial examples, implementation, test design, debugging and drafting. The prototype and its tests were developed with AI assistance. I do not present them as independently researched practitioner work.

Three key prompts I used were:

1. “Pick a high-friction, document-heavy niche area of finance.”
2. “Separation of deterministic vs. probabilistic layers (e.g., exact financial math/cited clauses vs. probabilistic extraction).”
3. “prepare the solution also and push it to my github … as a public repo, prepare very efficient solution as good as you can”

The live-extraction system prompt and its version, `borrowcheck-clause-extraction-v1`, are in `borrowcheck/extraction.py`. Successful optional model calls save messages, responses, model, usage and attempts in proposal metadata. No live model evaluation was performed for this repository; mocked transport responses are labelled tests. The development conversation is the primary record of AI-assisted drafting and implementation, not a fabricated runtime LLM transcript.

## 2. What I Rejected or Corrected

I used AI-assisted review and tests to reject or correct these choices:

- **Treating finance rules as universal defaults.** The researched agreement contains negotiated thresholds and exceptions. I label the demonstration terms as invented and require a facility-specific reviewed rule pack.
- **Equating a valid quote with a correct interpretation.** A test deliberately pairs a real 80% quote with an 81% proposal. Citation validation does not reject this semantic error. The model produces proposals; human review must check their meaning.
- **Trusting stored coordinates or control amounts without rechecking.** During implementation, line/PDF coordinates and control amounts could diverge from their cited evidence. Checks now rederive coordinates and require each monetary control to match its unique cited USD amount; regression tests cover both.
- **Describing the audit log as immutable or review as authenticated.** Local hashes and typed names provide neither. The README, UI and architecture identify them as demonstration controls.
- **Claiming testing that did not happen.** I report the 77 passing Python tests and ten acceptance outcomes, while separately stating that live-model quality, scanned-PDF OCR, practitioner savings and browser rendering have not been verified.

## 3. What Came From Me

My independent contribution was the design requirements and evaluation criteria: one specific finance problem, deterministic financial outputs, exact source traceability, explicit jurisdictional limits, human accountability and realistic edge cases. I also specified the submission identity, first-person presentation and public repository deliverable.

AI helped develop the borrowing-base niche, cross-ageing example, architecture, code and tests. I do not claim prior collateral-operations experience, practitioner interviews or an independently built implementation. My original requirements guided the work; the domain and operational assumptions still need independent validation.

## 4. One Thing I'd Stand Behind Without AI

The core component I would defend is the deterministic reconciliation and its assumptions. Cross-ageing removes A's entire $200,000, leaving an $800,000 pre-concentration pool. B's $300,000 is capped at $160,000; the other five debtors contribute $500,000. The $660,000 eligible pool advances at 80% to $528,000; subtracting the $50,000 reserve yields **$478,000**.

Omitting A's current $100,000 increases B's allowance by another $20,000. The resulting error is `80% × ($100,000 + $20,000) = $96,000`. I would explain the denominator, operation order, cent-flooring and one-deduction-per-dollar invariant before defending any output. Exact arithmetic remains conditional on complete, correctly interpreted and approved evidence.
