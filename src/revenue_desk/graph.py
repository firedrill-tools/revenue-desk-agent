"""LangGraph nodes separate evidence, model judgment, policy and each side effect."""
import json
import os
from dataclasses import dataclass
from typing import Literal, TypedDict
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from .workspace import Workspace


class Plan(BaseModel):
    intent: Literal["reconcile_paid", "credit", "review"]
    rationale: str = Field(min_length=5)
    email_body: str = Field(min_length=5)
    requested_slot: str | None = None


@dataclass(frozen=True)
class PlanningOutcome:
    plan: Plan | None
    observation: dict


class State(TypedDict, total=False):
    request_id: str
    invoice_id: str
    request: str
    approved_credit_cents: int
    context: dict
    plan: dict
    validated: dict
    result: dict
    plan_reused: bool


def model_plan(state: State) -> PlanningOutcome:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY required; no deterministic planner fallback")
    model_name = os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
    model = ChatOpenAI(model=model_name)
    response = model.with_structured_output(Plan, include_raw=True).invoke(
        "You are a revenue desk analyst. Decide whether the customer request is to reconcile a paid "
        "invoice, issue an explicitly approved credit, or ask for human review. Base your answer only "
        "on the supplied records. Never invent a payment or promise an action before execution. "
        "A paid selected invoice can coexist with other unpaid account invoices; use the full accounting balance when drafting account claims. "
        "If evidence conflicts, choose review. Draft an email only for an approved safe action.\n"
        + json.dumps({"request": state["request"], "approved_credit_cents": state["approved_credit_cents"],
                      "records": state["context"]}))
    raw = response.get("raw")
    metadata = getattr(raw, "response_metadata", None) or {}
    observation = {"source": "model_response", "requested_model": model_name,
                   "response_model": metadata.get("model_name") or metadata.get("model"),
                   "usage": getattr(raw, "usage_metadata", None), "cost_usd": None,
                   "parsed": response.get("parsing_error") is None and response.get("parsed") is not None}
    parsed = Plan.model_validate(response["parsed"]) if observation["parsed"] else None
    return PlanningOutcome(parsed, observation)


def build_graph(workspace: Workspace, planner=model_plan):
    def load(state: State):
        workspace.record(state["request_id"], state["invoice_id"], state["request"], state["approved_credit_cents"])
        return {"context": workspace.context(state["invoice_id"])}

    def plan(state: State):
        record = workspace.data["requests"][state["request_id"]]
        reused = record["plan"] is not None
        if record["plan"] is None:
            outcome = planner(state)
            if isinstance(outcome, Plan):
                outcome = PlanningOutcome(outcome, {"source": "injected_planner", "requested_model": None,
                    "response_model": None, "usage": None, "cost_usd": None, "parsed": True})
            record.setdefault("planning_observations", []).append(outcome.observation)
            if outcome.plan is None:
                record["status"] = "planning_failed"
                workspace.save()
                raise ValueError("model response did not contain a valid plan; observed usage retained in journal")
            record["plan"] = outcome.plan.model_dump()
            record["status"] = "started"
            workspace.save()
        return {"plan": record["plan"], "plan_reused": reused}

    def validate(state: State):
        record = workspace.data["requests"][state["request_id"]]
        if record["validated"] is None:
            choice = state["plan"]["intent"]
            invoice = state["context"]["invoice"]
            amount = state["approved_credit_cents"]
            if choice == "reconcile_paid" and invoice["paid_cents"] - invoice["credit_cents"] != invoice["total_cents"]:
                choice = "review"
            if choice == "credit" and (amount <= 0 or amount > invoice["paid_cents"] - invoice["credit_cents"]):
                choice = "review"
            if choice == "credit" and "credit" not in state["request"].lower():
                choice = "review"
            slot = state["plan"].get("requested_slot")
            if slot and slot not in state["context"]["calendar_slots"]:
                slot = None
            record["validated"] = {"intent": choice, "credit_cents": amount if choice == "credit" else 0,
                                   "slot": slot if choice != "review" else None}
            workspace.save()
        return {"validated": record["validated"]}

    def accounting(state: State):
        if state["validated"]["intent"] == "credit":
            workspace.apply(state["request_id"], "accounting", lambda: workspace.issue_credit(
                state["invoice_id"], state["validated"]["credit_cents"], state["request_id"]))
        return {}

    def crm(state: State):
        choice = state["validated"]["intent"]
        if choice == "review":
            return {}
        invoice = workspace.context(state["invoice_id"])["invoice"]
        account_id = invoice["account_id"]
        workspace.apply(state["request_id"], "crm", lambda: workspace.reconcile_crm(account_id))
        return {}

    def calendar(state: State):
        slot = state["validated"]["slot"]
        if slot:
            account_id = state["context"]["account"]["id"]
            workspace.apply(state["request_id"], "calendar", lambda: workspace.book(account_id, slot, state["request_id"]))
        return {}

    def email(state: State):
        if state["validated"]["intent"] == "review":
            return {}
        account = state["context"]["account"]
        body = state["plan"]["email_body"]
        workspace.apply(state["request_id"], "email", lambda: workspace.send_email(account["contact"], body, state["request_id"]))
        return {}

    def slack(state: State):
        account = state["context"]["account"]
        choice = state["validated"]["intent"]
        body = f"{state['invoice_id']}: {choice}. {state['plan']['rationale']}"
        workspace.apply(state["request_id"], "slack", lambda: workspace.post_slack(account["owner"], body, state["request_id"]))
        return {}

    def report(state: State):
        record = workspace.data["requests"][state["request_id"]]
        record["status"] = "complete"
        workspace.save()
        return {"result": {"request_id": state["request_id"], "intent": state["validated"]["intent"],
                           "completed_steps": record["done"][:], "plan_reused": state["plan_reused"],
                           "planning": (record.get("planning_observations") or [None])[-1]}}

    graph = StateGraph(State)
    for name, fn in [("load", load), ("plan", plan), ("validate", validate), ("accounting", accounting),
                     ("crm", crm), ("calendar", calendar), ("email", email), ("slack", slack), ("report", report)]:
        graph.add_node(name, fn)
    nodes = ["load", "plan", "validate", "accounting", "crm", "calendar", "email", "slack", "report"]
    graph.add_edge(START, nodes[0])
    for source, target in zip(nodes, nodes[1:]):
        graph.add_edge(source, target)
    graph.add_edge(nodes[-1], END)
    return graph.compile()
