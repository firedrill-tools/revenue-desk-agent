"""Synthetic domain actions; one JSON file, sequential execution only."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class Workspace:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text())

    def save(self):
        temporary_path = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf8", dir=self.path.parent,
                                    prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as staged:
                temporary_path = Path(staged.name)
                json.dump(self.data, staged, indent=2)
                staged.write("\n")
                staged.flush()
                os.fsync(staged.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def account_balance(self, account_id: str) -> int:
        return sum(max(0, invoice["total_cents"] - invoice["paid_cents"] - invoice["credit_cents"])
                   for invoice in self.data["invoices"] if invoice["account_id"] == account_id)

    def context(self, invoice_id: str):
        invoice = next((i for i in self.data["invoices"] if i["id"] == invoice_id), None)
        if invoice is None:
            raise ValueError(f"unknown invoice: {invoice_id}")
        account = next(a for a in self.data["accounts"] if a["id"] == invoice["account_id"])
        return {"invoice": invoice.copy(), "account": account.copy(),
                "account_invoices": [item.copy() for item in self.data["invoices"] if item["account_id"] == account["id"]],
                "accounting_balance_cents": self.account_balance(account["id"]),
                "calendar_slots": self.data["calendar_slots"][:]}

    def record(self, request_id: str, invoice_id: str, request: str, approved_credit_cents: int):
        record = self.data["requests"].get(request_id)
        if record and (record["invoice_id"], record["request"], record["approved_credit_cents"]) != (invoice_id, request, approved_credit_cents):
            raise ValueError("request ID reused with different input")
        if not record:
            record = {"invoice_id": invoice_id, "request": request, "plan": None,
                      "planning_observations": [],
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

    def reconcile_crm(self, account_id: str):
        account = next(a for a in self.data["accounts"] if a["id"] == account_id)
        account["crm_balance_cents"] = self.account_balance(account_id)
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
