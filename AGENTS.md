# Agent working notes

- Entrypoint: `revenue-desk`. The LangGraph is `src/revenue_desk/graph.py`.
- Each node represents evidence loading, model planning, policy validation or one business system effect. The OpenAI model is called through LangChain structured output.
- Synthetic state is a single JSON file with a per-request journal. Copy the fixture to a fresh file per independent case. Run sequentially; JSON writes are not cross-process transactional.
- Starter and busy fixtures embed dataset `synthetic-revenue-desk`, version 1. Keep account balances equal to the sum of outstanding invoice amounts for that account. The model context includes all account invoices; reconciling one paid invoice must not erase another unpaid invoice or change another account.
- `Workspace.save` stages and flushes before atomic replacement. A failed commit must leave the previous journal readable and remove its staged temporary file. Discard a workspace instance after an I/O error and reopen persisted state before retrying.
- Credit amount is an explicit CLI approval input. The model cannot invent approval; deterministic validation enforces paid-amount bounds and invoice facts.
- A committed node is skipped on a retry with the same request ID. Reusing an ID with changed invoice/request is rejected. The application does not connect to real payment rails.
- Planning observations retain requested/returned models and SDK-reported usage; unavailable measurements and cost remain null. `plan_reused` distinguishes a cached plan from a new planning call. Preserve observations from unparseable responses before rejecting the plan. Injected offline planners are labelled in their observations; never report those as live provider proof.
- No Firedrill integration until the new release is verified. Do not import the retired interface. No live-model proof has been performed from offline tests.
