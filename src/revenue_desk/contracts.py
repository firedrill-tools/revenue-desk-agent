"""Validate fictional ledger identity/amount relationships before planning."""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="allow")


class Account(Record):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    contact: str = Field(min_length=3)
    owner: str = Field(min_length=1)
    crm_balance_cents: int = Field(strict=True, ge=0)


class Invoice(Record):
    id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    total_cents: int = Field(strict=True, ge=0)
    paid_cents: int = Field(strict=True, ge=0)
    credit_cents: int = Field(strict=True, ge=0)
    credit_request_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def amounts(self):
        if self.credit_cents > self.paid_cents or self.paid_cents > self.total_cents:
            raise ValueError("Invalid invoice payment/credit relationship")
        return self


class WorkspaceData(Record):
    accounts: list[Account]
    invoices: list[Invoice]
    emails: list[dict[str, Any]]
    calendar_slots: list[str]
    meetings: list[dict[str, Any]]
    slack: list[dict[str, Any]]
    requests: dict[str, dict[str, Any]]

    @model_validator(mode="after")
    def relationships(self):
        accounts = {account.id for account in self.accounts}
        invoices = {invoice.id: invoice for invoice in self.invoices}
        if len(accounts) != len(self.accounts) or len(invoices) != len(self.invoices):
            raise ValueError("Duplicate account/invoice identity")
        seen_credits = set()
        for invoice in self.invoices:
            if invoice.account_id not in accounts:
                raise ValueError("Unknown invoice account")
            credited = 0
            for request_id in invoice.credit_request_ids:
                request = self.requests.get(request_id)
                if request_id in seen_credits or not request or request.get("invoice_id") != invoice.id:
                    raise ValueError("Orphan/duplicate credit request identity")
                amount = request.get("approved_credit_cents")
                if type(amount) is not int or amount <= 0:
                    raise ValueError("Credit history requires an exact approved amount")
                credited += amount
                seen_credits.add(request_id)
            if credited > invoice.credit_cents:
                raise ValueError("Credited request amounts exceed ledger credit")
        for request in self.requests.values():
            if request.get("invoice_id") not in invoices:
                raise ValueError("Unknown request invoice")
        if len(set(self.calendar_slots)) != len(self.calendar_slots):
            raise ValueError("Duplicate available slot")
        for key in ("emails", "meetings", "slack"):
            rows = getattr(self, key)
            identities = [row.get("request_id") for row in rows]
            if len(set(identities)) != len(rows) or any(identifier not in self.requests for identifier in identities):
                raise ValueError("Orphan/duplicate effect identity")
        occupied = [meeting.get("slot") for meeting in self.meetings]
        if len(set(occupied)) != len(occupied) or any(slot in self.calendar_slots for slot in occupied):
            raise ValueError("Calendar availability contradicts bookings")
        if any(meeting.get("account_id") not in accounts for meeting in self.meetings):
            raise ValueError("Unknown meeting account")
        return self
