# Revenue Desk agent

A LangGraph workflow reconciles one customer revenue request against synthetic accounting, CRM, calendar, email and Slack-style records. An OpenAI structured planning step interprets the request, then deterministic policy checks the accounting facts and any explicit credit approval before individual graph nodes commit side effects. Each request has a persistent step journal for reruns after partial completion.

## Run

Requires Python 3.12, `uv` and an OpenAI key for a model run.

```sh
uv sync --dev
cp fixtures/starter.json workspace.json
OPENAI_API_KEY=... uv run revenue-desk req-100 inv-410 \
  'Harbor says invoice 410 is paid. Reconcile the records and send a confirmation.'
uv run pytest
```

For a credit request, pass `--approved-credit-cents` with the already approved exact amount. Without that input, the model's suggestion cannot issue a credit. The accounting record is a synthetic ledger entry, never a payment processor. Inspect `workspace.json` for the request plan, validated action, completed nodes and final state. Use a new copy of the fixture to reset. Run one process at a time per workspace file.

The starter and busy fixtures identify dataset `synthetic-revenue-desk`, version `1`. The busy profile adds another partially paid Harbor invoice. To use it, create an ignored run directory, copy `fixtures/busy.json` there, and pass its path with `--workspace`. CRM reconciliation sums the nonnegative outstanding amounts of **all** invoices for the selected account. Reconciling paid `inv-410` therefore retains the 42,500-cent balance on `inv-412`, and an approved credit on `inv-410` does not erase another invoice's debt. Other accounts remain unchanged. The model receives the complete account invoice list and accounting balance alongside the selected invoice.

`OPENAI_MODEL` selects the planning model (default `gpt-6.1-sol`); export it and `OPENAI_API_KEY` through your shell or secret manager. The CLI emits its final JSON only after the report node completes. It includes `plan_reused` and the original planning observation: requested/returned model identifiers, provider-reported token usage when available, and `cost_usd: null` because no price is inferred. A reused plan's usage belongs to its original call; do not count it again as a new model execution. Missing measurements stay null. If a model response cannot be parsed, the journal retains its available usage and the request stops before business actions.

Workspace saves stage and flush a temporary file before replacing the prior journal. A failed replacement leaves the previous file readable. This protects against partial file writes while preserving the single-writer restriction; it does not add cross-process transactions. After an I/O failure, discard the in-memory workspace and inspect/reopen its persisted file before retrying with the original request ID and unchanged input.

`scenarios/README.md` covers stale CRM state, payment contradiction, approval limits, duplicate financial actions, busy accounts and recovery after partial failure. The graph's step journal is useful for local synthetic actions; it does not by itself guarantee exactly-once behavior if later connected to remote systems that can succeed without returning a response. Such connectors need their own idempotency keys or outcome review.

The 13 offline tests use injected planning outcomes or scripted SDK messages to verify policy, account-wide balances, restarted journal recovery, atomic-save failure, unknown/reported usage and cached-plan behavior. The busy-account regression reproduced an incorrect zero balance before the fix. These tests do not replace the model in the actual application. No live model call has been made here, so provider behavior and actual usage remain unmeasured. The thin Firedrill connection waits for the new official release. No public license has been selected.

Explore related applications in the [Firedrill example catalog](https://github.com/firedrill-tools/firedrill-example-catalog). Product and setup references: [Firedrill](https://firedrill.run/) and the [official developer documentation](https://docs.firedrill.run/). Use documentation matching the qualified release; this repository records its current integration limits above.
