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

`scenarios/README.md` covers stale CRM state, payment contradiction, approval limits, duplicate financial actions and partial failure. The graph's step journal is useful for local synthetic actions; it does not by itself guarantee exactly-once behavior if later connected to remote systems that can succeed without returning a response. Such connectors need their own idempotency keys or outcome review.

The offline suite uses an injected planner to verify the policy and cross-system state. It does not replace the model in the actual application. No live model call has been made here, so model quality, usage and prompts remain unmeasured. The thin Firedrill connection waits for the new official release. No public license has been selected.
