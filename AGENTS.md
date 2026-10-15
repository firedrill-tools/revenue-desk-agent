# Agent working notes

- Entrypoint: `revenue-desk`. The LangGraph is `src/revenue_desk/graph.py`.
- Each node represents evidence loading, model planning, policy validation or one business system effect. The OpenAI model is called through LangChain structured output.
- Synthetic state is a single JSON file with a per-request journal. Copy the fixture to a fresh file per independent case. Run sequentially; JSON writes are not cross-process transactional.
- Credit amount is an explicit CLI approval input. The model cannot invent approval; deterministic validation enforces paid-amount bounds and invoice facts.
- A committed node is skipped on a retry with the same request ID. Reusing an ID with changed invoice/request is rejected. The application does not connect to real payment rails.
- No Firedrill integration until the new release is verified. Do not import the retired interface. No live-model proof has been performed from offline tests.
