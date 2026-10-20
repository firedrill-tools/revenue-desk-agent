# Revenue desk agent with LangGraph and OpenAI

A LangGraph workflow reconciles a customer request across synthetic accounting, CRM, calendar, email and Slack records. An OpenAI structured planning step interprets the request. Separate graph nodes validate policy and commit each system effect. The saved request journal supports recovery after partial completion and preserves original planning evidence.

## Simulate with Firedrill

[Firedrill](https://firedrill.run/) is a simulation platform for AI agents.
Start from this repository’s root:

```sh
npx firedrill-run init
```

Sign in and choose your project, then follow the [simulation run guide](firedrill/README.md)
for application dependencies, a preview and the reviewed scenarios. Your agent runs
locally or in your CI; model credentials stay separate from Firedrill sign-in.
The included recipes record outcomes without an automatic quality score or CI gate.

## Run one request

Requires Python 3.12 and `uv`. Listing and initialization make no model calls and need no credentials.

```sh
uv sync --dev --locked
uv run revenue-desk --list-cases
uv run revenue-desk --init-case busy --workspace .runs/busy.json
OPENAI_API_KEY=... uv run revenue-desk req-100 inv-410 \
  'Reconcile the paid invoice and send an accurate confirmation.' --workspace .runs/busy.json
```

Initialization prints the selected case's exact task arguments. The CLI prints completed result JSON only after the graph's report node. Inspect the workspace's `requests` journal after a nonzero exit; it can contain committed work. An unchanged completed request returns its original result/observation with `replayed: true` and `plan_reused: true`, without another model or effect. Reusing the ID with another invoice, request or approval is rejected.

`OPENAI_MODEL` selects the planner (default `gpt-6.1-sol`). Model availability and task quality remain to be verified live. `OPENAI_BASE_URL` optionally selects an HTTPS API endpoint or loopback HTTP test endpoint. Missing credentials do not select an offline planner. The normal application uses real model calls; deterministic planners exist only as explicit test injections.

For an already authorized credit, the trusted caller supplies the **exact integer amount** with `--approved-credit-cents 2000`. The model cannot invent this approval. Policy requires an explicit credit request, a positive approved amount and enough paid value after earlier credits. Zero approval or an over-limit amount goes to review. The example uses one synthetic currency's integer cents; it is not a payment processor, FX engine or authorization service.

## Model and graph boundaries

The qualified path is `langgraph==1.2.15` → `langchain-openai==1.7.2` → OpenAI Python `3.31.0` / httpx2 `2.13.1`. LangChain requests strict JSON-schema output through **Chat Completions**. It makes one HTTP attempt, with a 30-second timeout, 4,096 output tokens, streaming/cache/storage disabled. Only one `stop` choice with a non-refused valid plan is accepted. The [structured-output completion/refusal contract](https://developers.openai.com/api/docs/guides/structured-outputs) describes why incomplete output cannot be accepted merely because its JSON looks usable.

HTTP observations are retained before SDK parsing: returned model/response/request IDs, finish state, raw message/usage and protocol errors. The journal also records the parsed SDK message, input/prompt hashes and dependency versions. Failed responses retain their available usage; absent/partial counters are unknown, distinct from reported zero. `planning_attempts` and `all_attempt_usage` cover original attempts only when all measurements are complete. A reused plan's usage is not a new call. Cost is always unknown; no price or billing total is inferred.

The model sees the request, exact caller approval, selected account/invoice, **all invoices on that account**, calculated accounting balance and currently available slots. It cannot read the manifest, scenario criteria, unrelated accounts or journal. Email content/rationale remain model judgments; tests do not establish their factual quality. Email recipients and Slack owners come from the selected account, and calendar booking is limited to an available slot.

## Cross-system state and recovery

CRM balance sums outstanding amounts across the selected account. The busy profile retains a 42,500-cent debt on separate `inv-412` when paid `inv-410` is reconciled or credited. An individual credit must not erase another invoice's debt. Other accounts and prior messages/bookings remain intact.

| Situation | Behavior |
| --- | --- |
| Paid selected invoice; stale CRM | Reconcile account-wide balance, optional available meeting, customer email and owner notice |
| Missing payment, unapproved/over-limit credit | Review; no credit, CRM update or customer email; internal notice records the decision |
| Model/provider failure | Preserve planning observation; no business effect; explicit retry can plan again |
| Failure after a committed node | Reopen with the same input; reuse plan and skip committed nodes |
| Relevant records changed before resumption | Retain original plan, require review and suppress further customer/financial/calendar actions |
| Complete unchanged replay | Read-only original result; no new model/effect even if later records changed |

Each local effect and its completed journal marker publish in one atomic JSON replacement. A failed action/publication leaves that step uncommitted and restores its in-memory state. Earlier committed steps remain. Each successful step updates the expected business-context hash; later corrections to accounting, account or calendar state trigger review before cached approval can continue. Already committed effects are not undone. Context/ledger schemas reject duplicate identities, fractional/negative amounts, orphan credit IDs and contradictory bookings before planning.

Run **one writer per workspace file**. The graph reloads persisted state on each invocation and saves through a private staged file, flush/fsync and atomic replacement. This prevents partial local-file writes; it is not a cross-process transaction/lock or exactly-once guarantee for future remote services. After an I/O error, inspect/reopen persisted state before retrying. There are no connected real accounting, CRM, email, calendar or Slack services in this repository.

## Dataset 2.0.0

`synthetic-revenue-desk` **2.0.0** replaces the original two-profile version 1 with ten cases:

| Profile | Cases | Starting conditions |
| --- | --- | --- |
| Starter | `starter`, `approved-credit` | Two accounts; stale CRM with a paid invoice; exact caller approval for the credit case |
| Busy | `busy`, `busy-credit` | Twelve accounts, twenty-three invoices, two completed cross-system requests, two emails/notices and a prior booking/credit |
| Ambiguous | `payment-claim`, `conflicting-owner` | Customer payment claim contradicts accounting; owner notes disagree |
| Boundary | `unapproved-credit`, `no-slots`, `prior-complete`, `hostile-note` | No approval, unavailable calendar, original completed-credit replay or malicious stored instructions |

The manifest binds exact workspace bytes and suggested task inputs. Listing validates every digest, embedded dataset identity and business relationship. `--init-case CASE --workspace NEW_PATH` copies verified bytes into a fresh private file and refuses overwrite. Reset coverage is local JSON only. `scripts/build_fixtures.py` reproduces all bytes; the wheel bundles the same inputs. Historical decisions are explicitly `synthetic_fixture_history` with unknown model usage, not recorded target executions. The request journal records the actual starting file hash and declared dataset; changing a prompt creates a different input hash while the starting-state identity remains the same.

Choose fresh paths for independent situations/trials. Stop the owning process before resetting its file. Stopping observation or reaching a client timeout does not prove provider-side generation/cost stopped. The synchronous application creates no worker, scheduler or persistent job. Its constructed HTTP/OpenAI clients close on success/failure; local JSON is the only owned business state.

## Verification and remaining gates

```sh
uv run --no-sync pytest -q
uv build --wheel
uv run --no-sync python scripts/check_wheel.py
```

**53 offline checks passed.** Native checks retain the actual LangGraph, LangChain and OpenAI implementations and replace only HTTP transport. They cover strict schema serialization, finish/refusal/invalid output, retained failed usage, missing/zero counters, one attempt on 503, client cleanup, CLI success/failure and original evidence on replay. Policy/state checks reproduce a payment correction being ignored after partial failure and verify the fix, atomic local effects, restarted credit recovery and preservation of unrelated busy state. All ten initialized cases run through the graph with explicitly injected planners to check their local boundaries. Packaged selection/initialization also runs outside the checkout without credentials.

These are application/SDK proofs, not live model judgments, billing or connected-backend qualification. [Scenario briefs](scenarios/README.md) use semantic criteria for prose and exact checks for financial effects; no overall score is fabricated. Provider access and authenticated persisted Firedrill runs remain parked. The included [Firedrill integration](firedrill/README.md) invokes the real application. Publication and licensing are still undecided.

Related applications: [Firedrill example catalog](https://github.com/firedrill-tools/firedrill-example-catalog). Product/setup references: [Firedrill](https://firedrill.run/) and [official developer documentation](https://docs.firedrill.run/). Use documentation matching the qualified release.

## Current Firedrill connection — 2026-10-19

The [agent-first integration](firedrill/README.md) pins released CLI/SDK 2.2.2 and invokes the actual application CLI with fresh private state. Caller credit amounts/approval identities remain explicit and independent of case selection. Earlier pending-release notes are historical; authenticated persisted and live model proofs remain pending.
