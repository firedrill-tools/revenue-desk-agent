# Simulate this agent with Firedrill

Firedrill is a simulation platform for AI agents. Your coding agent can prepare
and operate these simulations; the application and its model run in your own
repository or CI.

Start in the repository root, not inside `firedrill/`:

```sh
npx firedrill-run init
```

Authorize Firedrill and select a project/environment. Installation choices are
optional; skip them when using the locked `firedrill/` toolchain below. This setup
does not invoke the target agent or grant it access to real business accounts.

The separate optional execution toolchain exact-pins released CLI and TypeScript SDK **2.2.2**, verified October 19, 2026. Node 22+ is required. Application/framework/provider dependencies remain in the original Python lockfile; this uses the documented command target.

## Prepare and authorize

From the repository root with `uv` on PATH:

```sh
uv sync --locked --dev
npm ci --prefix firedrill --ignore-scripts --no-audit --no-fund
firedrill_cli=firedrill/node_modules/@firedrill-run/cli/bin/firedrill.mjs
node "$firedrill_cli" validate firedrill/scenario.json --json --non-interactive
```

Offline validation allocates no batch. Select the actual project/environment with `npx firedrill-run init` in a human terminal. Automation supplies `FIREDRILL_TOKEN`, `FIREDRILL_PROJECT_ID` and `FIREDRILL_ENVIRONMENT_ID` through its secret store. The application independently needs `OPENAI_API_KEY` and an enabled `OPENAI_MODEL` or recipe `configuration.parameters.model`. Keep credentials out of recipes and Git.

## Execute the actual application

With an authorized provider budget:

```sh
node firedrill/simulate.mjs --preview
node "$firedrill_cli" simulate firedrill/scenario.json --scenario starter --json --non-interactive
```

The target initializes a hash-bound private case and invokes the actual `revenue-desk` CLI and LangGraph reconciliation runtime. It preserves original application completion, partial effects, raw/SDK usage distinctions and failures. Invoking reconciliation requests the existing local CRM/email/calendar/Slack bookkeeping. Credit approval is an independent exact nonnegative integer input; the model and case selector cannot invent an amount. The recipe includes paid-invoice reconciliation, approved credit, unapproved credit and a completed fictional-history replay.

The full recipe has one repetition, explicit maximum runs and concurrency one. `node firedrill/simulate.mjs` executes the same full recipe using the SDK. Completed-record replay is real application recovery over imported fictional history; it makes no fresh model trial and does not fabricate historical model measurements. Existing per-application request/deadline bounds apply, not provider billing guarantees.

Each invocation retains a fresh private `.runs/firedrill/attempt-*` workspace. New attempts never reset old business state or evidence. Output contains the actual CLI result under `application` and runner-local state paths under `localState`; paths are not uploaded artifacts. Failures retain partial stdout/stderr and the private directory. Earlier committed effects survive later errors. All financial/outbox records here are local and fictional; no payment rails, real accounting service or customer mailbox is connected.

The adapter accepts invocation version `2026-10-17-target-invocation.1`, ID-only scenario context and explicit task fields. Controller/evaluation data and unsupported Firedrill Tool bindings are rejected. Operator/CI credentials are removed before application dispatch. The local dependency seam needs no Firedrill synthetic Tool. State reset does not erase provider retention/billing or prove remote cancellation/rollback.

## Operator MCP, recovery and CI

Configure remote OAuth MCP **https://mcp.firedrill.run/mcp** with the [host-specific setup](https://docs.firedrill.run/guides/coding-agents); no local MCP package is required. Host OAuth and CLI/SDK login are separate. MCP prepares/queues/inspects; the local runner executes the actual application. Attach an existing batch with `node firedrill/simulate.mjs --run BATCH_ID`.

Preserve the operation ID and private journal after uncertainty. Use `--resume OPERATION_ID` to recover that execution or `--result BATCH_ID` for a retained read. A fresh simulation is new work, and a new adapter invocation gets a fresh private case. Runner exit codes preserve pending work/assessment, errors and optional gates. Execution completion is distinct from correct business behavior; this observation-only recipe requests no grading or gate.

Ordinary CI is offline. Use the [live CI generator](https://docs.firedrill.run/guides/ci) only with actual scope, protected credentials and selected budgets. Authenticated persisted happy/negative runs, live model quality/cost, real financial/account connectors, and licensing remain separate gates.

References: [SDK](https://docs.firedrill.run/sdk/typescript), [command targets](https://docs.firedrill.run/guides/callbacks), [operator MCP](https://docs.firedrill.run/guides/control-mcp).

Before application dispatch, each private workspace saves the validated outer run/attempt/scenario IDs in `invocation.json`. This maps interrupted runs to local state; it is separate from the SDK recovery journal and grants no application authority.

## Offline verification

After installing the application dependencies and locked integration toolchain,
run `npm test --prefix firedrill` to exercise the adapter checks. These checks are
optional for first use and call no paid model. The Node 22+ requirement above is
for the Firedrill clients; it does not lower any application runtime requirement
in the root README.
