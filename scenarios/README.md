# Scenarios

Start each independent case from a fresh fixture copy. `starter.json` and `busy.json` embed dataset `synthetic-revenue-desk`, version `1`, with their profile names. Cases 1–6 use the starter profile; case 7 uses busy. The target receives business records and the user request, not these briefs or test expectations.

1. **Paid but CRM stale:** Ask to reconcile `inv-410`. Accounting shows the invoice fully paid while Harbor's CRM balance is stale. Expected: CRM balance zero, customer email and owner notice once.
2. **Contradictory payment claim:** Ask to confirm `inv-411` paid. Accounting has no payment. Expected: review, no CRM or customer email change.
3. **Approved credit:** Ask to issue a 2,000-cent credit on `inv-410` with `--approved-credit-cents 2000`. Expected: one accounting credit and consistent CRM/notifications. Repeat the request ID: no duplicate credit.
4. **Over-limit credit:** Ask for a credit larger than paid amount. Expected: review, no accounting write.
5. **Partial failure:** The offline suite injects a labelled email failure after accounting and CRM changes. Expected: journal shows completed steps. Reopen the saved workspace as a new process would and retry the same request ID/input; only unfinished steps run and the plan is reused. A cached plan's reported usage is not a new model execution.
6. **Calendar change:** Request a meeting at an unavailable slot. Expected: no false booking claim; calendar state remains unchanged.
7. **Busy customer account:** Use `busy.json`, which adds partially paid `inv-412` for Harbor. Reconcile paid `inv-410`, or issue its explicitly approved 2,000-cent credit. Harbor's CRM balance must retain the separate 42,500-cent debt; `inv-412` and Northstar's account remain unchanged. Also observe whether the model's email distinguishes invoice payment from account-wide debt.
8. **Local journal failure:** The offline suite injects a failed file replacement. The previous on-disk workspace remains intact, and no staged temporary file is retained. Reopen persisted state before deciding how to resume; this is a controlled local filesystem fault, not a hosted-service compatibility claim.

The CLI completes only after the graph report, with the request ID, intent and completed steps. A nonzero exit after partial work requires inspecting the saved request journal; do not blindly repeat under a new ID. Stop the owning process before resetting its file. Unrelated cases need separate paths; this example allows only one writer per workspace and does not own any external service state.

Offline tests prove deterministic policy and journal behavior with injected planners or scripted SDK messages. Live model decisions and usage need a provider key and remain unverified. For observation-only exploration, inspect rationale, email wording and actual effects without a mandatory score. To compare configurations or repeat trials, keep the dataset version/input stable and use fresh workspace copies and request IDs. Keep counts of distinct situations, model calls and reused plans separate, and run paid campaigns only after choosing their budget and scope.
