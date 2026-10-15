from pathlib import Path
import pytest
from revenue_desk.graph import Plan, build_graph, model_plan
from revenue_desk.workspace import Workspace

FIXTURE = Path(__file__).parents[1] / "fixtures" / "starter.json"


def setup(tmp_path):
    path = tmp_path / "workspace.json"
    path.write_text(FIXTURE.read_text())
    return Workspace(path)


def run(workspace, planner, request_id="req-1", invoice_id="inv-410",
        request="Reconcile paid invoice", approved_credit_cents=0):
    return build_graph(workspace, planner).invoke({"request_id": request_id,
        "invoice_id": invoice_id, "request": request,
        "approved_credit_cents": approved_credit_cents})["result"]


def planned(intent):
    return lambda _: Plan(intent=intent, rationale="Records support this action",
                          email_body="We have updated your account records.")


def test_paid_invoice_reconciles_all_systems_and_retry(tmp_path):
    workspace = setup(tmp_path)
    result = run(workspace, planned("reconcile_paid"))
    assert result["intent"] == "reconcile_paid"
    assert workspace.data["accounts"][0]["crm_balance_cents"] == 0
    assert len(workspace.data["emails"]) == len(workspace.data["slack"]) == 1
    run(workspace, lambda _: pytest.fail("planner must be reused"))
    assert len(workspace.data["emails"]) == len(workspace.data["slack"]) == 1


def test_payment_contradiction_goes_to_review(tmp_path):
    workspace = setup(tmp_path)
    result = run(workspace, planned("reconcile_paid"), invoice_id="inv-411",
                 request="Confirm this invoice has been paid")
    assert result["intent"] == "review"
    assert workspace.data["accounts"][1]["crm_balance_cents"] == 84000
    assert workspace.data["emails"] == []
    assert len(workspace.data["slack"]) == 1


def test_approved_credit_exactly_once_and_over_limit_review(tmp_path):
    workspace = setup(tmp_path)
    run(workspace, planned("credit"), request="Issue the approved credit",
        approved_credit_cents=2000)
    run(workspace, lambda _: pytest.fail("planner must be reused"),
        request="Issue the approved credit", approved_credit_cents=2000)
    assert workspace.data["invoices"][0]["credit_cents"] == 2000
    assert workspace.data["invoices"][0]["credit_request_ids"] == ["req-1"]
    result = run(workspace, planned("credit"), request_id="req-2",
                 request="Issue another approved credit", approved_credit_cents=200000)
    assert result["intent"] == "review"
    assert workspace.data["invoices"][0]["credit_cents"] == 2000


def test_partial_failure_resumes_without_replanning_or_duplicate_action(tmp_path):
    workspace = setup(tmp_path)
    original = workspace.send_email
    attempted = []
    def fail_once(*args):
        attempted.append(1)
        if len(attempted) == 1:
            raise RuntimeError("email unavailable")
        return original(*args)
    workspace.send_email = fail_once
    with pytest.raises(RuntimeError, match="email unavailable"):
        run(workspace, planned("credit"), request="Issue approved credit", approved_credit_cents=1500)
    assert workspace.data["requests"]["req-1"]["done"] == ["accounting", "crm"]
    run(workspace, lambda _: pytest.fail("planner must be reused"),
        request="Issue approved credit", approved_credit_cents=1500)
    assert workspace.data["invoices"][0]["credit_cents"] == 1500
    assert len(workspace.data["emails"]) == len(workspace.data["slack"]) == 1


def test_request_id_cannot_change_approval(tmp_path):
    workspace = setup(tmp_path)
    run(workspace, planned("reconcile_paid"))
    with pytest.raises(ValueError, match="reused"):
        run(workspace, planned("credit"), approved_credit_cents=1000)


def test_live_planner_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        model_plan({})
