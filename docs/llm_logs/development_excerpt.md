# Selected development conversation excerpts

These are actual selected messages from the development conversation, not a reconstructed full transcript. The code and written artifacts in this repository are AI-assisted outputs from that work. The complete original ChatGPT conversation should accompany the assignment's separate chat-log upload; this excerpt does not claim to replace that export.

## User: prototype request

> prepare the solution also and push it to my github https://github.com/mohitkumarr373 as a public repo, prepare very efficient solution as good as you can and keep everything like i have did that

## Assistant: independent calculation check

> The calculation engine now passes 41 tests, including randomized comparisons against an independent exact-arithmetic calculation. I’m finishing the AI proposal checks, review workflow, and documentation before publishing the repository.

## Assistant: semantic failure found

> One test exposes a key limitation: a model can attach a real source quote to the wrong percentage. The prototype therefore requires human review of extracted terms before they can become calculation rules. I’m documenting this explicitly and checking the browser workflow next.

## Assistant: intermediate test and performance result

> The suite now passes all 74 tests. The core engine also processed 100,000 synthetic invoices in a median of 0.40 seconds across three runs; that measurement excludes file loading, document extraction, and network calls.

The final suite subsequently grew to 77 tests. Final results supersede these intermediate progress counts.

## Runtime extraction logs

There were **zero live OpenRouter calls** during the delivered evaluation. The bundled local parser is deterministic. Mock adapter tests are not live model transcripts. The exact optional runtime system prompt is preserved in `runtime_system_prompt.txt`; successful live runs save their actual messages and responses under `metadata.llm_log` in the proposal output. Private runtime logs remain git-ignored by default.
