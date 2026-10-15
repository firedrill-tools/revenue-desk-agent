"""Synthetic domain actions; one JSON file, sequential execution only."""
import json
from pathlib import Path


class Workspace:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text())

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2) + "\n")

    def context(self, invoice_id: str):
        invoice = next((i for i in self.data["invoices"] if i["id"] == invoice_id), None)
        if invoice is None:
            raise ValueError(f"unknown invoice: {invoice_id}")
        account = next(a for a in self.data["accounts"] if a["id"] == invoice["account_id"])
        return {"invoice": invoice.copy(), "account": account.copy(),
                "calendar_slots": self.data["calendar_slots"][:]}

    def record(self, request_id: str, invoice_id: str, request: str, approved_credit_cents: int):
        record = self.data["requests"].get(request_id)
        if record and (record["invoice_id"], record["request"], record["approved_credit_cents"]) != (invoice_id, request, approved_credit_cents):
            raise ValueError("request ID reused with different input")
        if not record:
            record = {"invoice_id": invoice_id, "request": request, "plan": None,
                      "approved_credit_cents": approved_credit_cents,
                      "validated": None, "done": [], "status": "started"}
            self.data["requests"][request_id] = record
            self.save()
        return record

    def mark(self, request_id: str, step: str):
        done = self.data["requests"][request_id]["done"]
        if step not in done:
            done.append(step)
            self.save()

    def apply(self, request_id: str, step: str, action):
        if step in self.data["requests"][request_id]["done"]:
            return
        action()
        self.mark(request_id, step)

    def issue_credit(self, invoice_id: str, amount_cents: int, request_id: str):
        invoice = next(i for i in self.data["invoices"] if i["id"] == invoice_id)
        if request_id in invoice.get("credit_request_ids", []):
            return
        if invoice["credit_cents"] + amount_cents > invoice["paid_cents"]:
            raise ValueError("credit exceeds paid amount")
        invoice["credit_cents"] += amount_cents
        invoice.setdefault("credit_request_ids", []).append(request_id)
        self.save()

    def reconcile_crm(self, account_id: str, balance_cents: int):
        account = next(a for a in self.data["accounts"] if a["id"] == account_id)
        account["crm_balance_cents"] = balance_cents
        self.save()

    def book(self, account_id: str, slot: str, request_id: str):
        if any(m["request_id"] == request_id for m in self.data["meetings"]):
            return
        if slot not in self.data["calendar_slots"]:
            raise ValueError("calendar slot unavailable")
        self.data["calendar_slots"].remove(slot)
        self.data["meetings"].append({"request_id": request_id, "account_id": account_id, "slot": slot})
        self.save()

    def send_email(self, to: str, body: str, request_id: str):
        if not any(e["request_id"] == request_id for e in self.data["emails"]):
            self.data["emails"].append({"request_id": request_id, "to": to, "body": body})
            self.save()

    def post_slack(self, owner: str, body: str, request_id: str):
        if not any(m["request_id"] == request_id for m in self.data["slack"]):
            self.data["slack"].append({"request_id": request_id, "owner": owner, "body": body})
            self.save()
