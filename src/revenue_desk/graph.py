"""LangGraph nodes separate evidence, model judgment, policy and each side effect."""
from typing import TypedDict
from pydantic import BaseModel, Field, field_validator
from langgraph.graph import StateGraph, START, END
from .workspace import Workspace
from .model import Plan, PlanningOutcome, model_plan


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
    replayed: bool
    context_changed: bool


class Request(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    invoice_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    request: str = Field(min_length=5, max_length=4000)
    approved_credit_cents: int = Field(strict=True, ge=0)

    @field_validator("request")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Request cannot be blank")
        return value


def build_graph(workspace: Workspace, planner=model_plan):
    def load(state: State):
        Request.model_validate({key: state.get(key) for key in Request.model_fields})
        workspace.reload()
        context = workspace.context(state["invoice_id"])
        record = workspace.record(state["request_id"], state["invoice_id"], state["request"], state["approved_credit_cents"])
        if record["status"] == "complete":
            result = dict(record.get("result") or {"request_id": state["request_id"], "intent": record["validated"]["intent"],
                "completed_steps": record["done"][:], "planning": (record.get("planning_observations") or [None])[-1]})
            result.update({"plan_reused": True, "replayed": True})
            return {"result": result, "replayed": True}
        digest = workspace.context_hash(state["invoice_id"])
        changed = record["plan"] is not None and record.get("execution_context_sha256") != digest
        if changed:
            record.setdefault("context_changes", []).append({"expected": record.get("execution_context_sha256"), "observed": digest})
            record["requires_review"] = True
        elif record["plan"] is None:
            record["execution_context_sha256"] = digest
        workspace.save()
        return {"context": context, "context_changed": changed, "replayed": False}

    def plan(state: State):
        record = workspace.data["requests"][state["request_id"]]
        reused = record["plan"] is not None
        if record["plan"] is None:
            try:
                outcome = planner(state)
            except Exception as error:
                record.setdefault("planning_observations", []).append({"source": "planner_error", "error_type": type(error).__name__, "usage": None, "cost_usd": None, "parsed": False})
                record["status"] = "planning_failed"
                workspace.save()
                raise
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
        if record.get("requires_review"):
            record["validated"] = {"intent": "review", "credit_cents": 0, "slot": None}
            workspace.save()
        elif record["validated"] is None:
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
        reason = "Records changed since the original plan; review before further action." if workspace.data["requests"][state["request_id"]].get("requires_review") else state["plan"]["rationale"]
        body = f"{state['invoice_id']}: {choice}. {reason}"
        workspace.apply(state["request_id"], "slack", lambda: workspace.post_slack(account["owner"], body, state["request_id"]))
        return {}

    def report(state: State):
        record = workspace.data["requests"][state["request_id"]]
        record["status"] = "complete"
        observations = record.get("planning_observations") or []
        keys = ("input_tokens", "output_tokens", "total_tokens")
        complete = bool(observations) and all(isinstance(item.get("usage"), dict) and
            all(type(item["usage"].get(key)) is int and item["usage"][key] >= 0 for key in keys) for item in observations)
        record["result"] = {"request_id": state["request_id"], "intent": state["validated"]["intent"],
                           "completed_steps": record["done"][:], "plan_reused": state["plan_reused"],
                           "replayed": False, "context_changed": bool(record.get("requires_review")),
                           "initial_state_sha256": record.get("initial_state_sha256"), "dataset": record.get("dataset"),
                           "planning_attempts": len(observations), "all_attempt_usage_complete": complete,
                           "all_attempt_usage": {key: sum(item["usage"][key] for item in observations) for key in keys} if complete else None,
                           "cost_usd": None,
                           "planning": (record.get("planning_observations") or [None])[-1]}
        workspace.save()
        return {"result": record["result"]}

    graph = StateGraph(State)
    for name, fn in [("load", load), ("plan", plan), ("validate", validate), ("accounting", accounting),
                     ("crm", crm), ("calendar", calendar), ("email", email), ("slack", slack), ("report", report)]:
        graph.add_node(name, fn)
    nodes = ["load", "plan", "validate", "accounting", "crm", "calendar", "email", "slack", "report"]
    graph.add_edge(START, nodes[0])
    graph.add_conditional_edges("load", lambda state: "done" if state.get("replayed") else "plan", {"done": END, "plan": "plan"})
    for source, target in zip(nodes[1:], nodes[2:]):
        graph.add_edge(source, target)
    graph.add_edge(nodes[-1], END)
    return graph.compile()
