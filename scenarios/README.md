# Scenarios

Start each independent case from a fresh `fixtures/starter.json` copy.

1. **Paid but CRM stale:** Ask to reconcile `inv-410`. Accounting shows the invoice fully paid while Harbor's CRM balance is stale. Expected: CRM balance zero, customer email and owner notice once.
2. **Contradictory payment claim:** Ask to confirm `inv-411` paid. Accounting has no payment. Expected: review, no CRM or customer email change.
3. **Approved credit:** Ask to issue a 2,000-cent credit on `inv-410` with `--approved-credit-cents 2000`. Expected: one accounting credit and consistent CRM/notifications. Repeat the request ID: no duplicate credit.
4. **Over-limit credit:** Ask for a credit larger than paid amount. Expected: review, no accounting write.
5. **Partial failure:** Fail email after accounting and CRM changes. Expected: journal shows completed steps. Retry same request ID with same input and only unfinished steps run; plan is reused.
6. **Calendar change:** Request a meeting at an unavailable slot. Expected: no false booking claim; calendar state remains unchanged.

Offline tests prove deterministic policy and journal behavior with an injected planner. Live model decisions and usage need a provider key and remain unverified.
