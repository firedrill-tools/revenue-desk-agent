from pathlib import Path
import pytest
from revenue_desk.graph import Plan, build_graph, model_plan
from revenue_desk.workspace import Workspace
from langchain_core.messages import AIMessage

FIXTURE = Path(__file__).parents[1] / "fixtures" / "starter.json"


def setup(tmp_path, fixture=FIXTURE):
    path = tmp_path / "workspace.json"
    path.write_text(fixture.read_text())
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


@pytest.mark.parametrize("intent,amount,prompt", [
    ("reconcile_paid", 0, "Reconcile the paid invoice"),
    ("credit", 2000, "Issue the approved credit"),
])
def test_account_reconciliation_preserves_other_invoice_balances(tmp_path, intent, amount, prompt):
    workspace = setup(tmp_path, FIXTURE.with_name("busy.json"))
    other_invoice = workspace.data["invoices"][2].copy()
    other_account = workspace.data["accounts"][1].copy()
    context = workspace.context("inv-410")
    assert {invoice["id"] for invoice in context["account_invoices"]} == {"inv-410", "inv-412"}
    assert context["accounting_balance_cents"] == 42500
    run(workspace, planned(intent), request=prompt, approved_credit_cents=amount)
    assert workspace.data["accounts"][0]["crm_balance_cents"] == 42500
    assert workspace.data["invoices"][2] == other_invoice
    assert workspace.data["accounts"][1] == other_account
    assert workspace.data["invoices"][0]["credit_cents"] == amount


def test_busy_account_recovers_from_a_new_process_without_duplicate_credit(tmp_path):
    workspace = setup(tmp_path, FIXTURE.with_name("busy.json"))
    def unavailable(*_args):
        raise RuntimeError("email unavailable after accounting commit")
    workspace.send_email = unavailable
    with pytest.raises(RuntimeError, match="email unavailable"):
        run(workspace, planned("credit"), request="Issue approved credit", approved_credit_cents=4000)
    restarted = Workspace(workspace.path)
    run(restarted, lambda _: pytest.fail("persisted plan must be reused"), request="Issue approved credit", approved_credit_cents=4000)
    assert restarted.data["invoices"][0]["credit_cents"] == 4000
    assert restarted.data["invoices"][0]["credit_request_ids"] == ["req-1"]
    assert restarted.data["accounts"][0]["crm_balance_cents"] == 42500
    assert len(restarted.data["emails"]) == len(restarted.data["slack"]) == 1


def test_failed_journal_replacement_keeps_the_previous_workspace(tmp_path, monkeypatch):
    workspace = setup(tmp_path)
    original = workspace.path.read_bytes()
    workspace.data["accounts"][0]["crm_balance_cents"] = 0
    def failed_replace(*_args):
        raise OSError("synthetic disk failure at commit")
    monkeypatch.setattr("revenue_desk.workspace.os.replace", failed_replace)
    with pytest.raises(OSError, match="disk failure"):
        workspace.save()
    assert workspace.path.read_bytes() == original
    assert Workspace(workspace.path).data["accounts"][0]["crm_balance_cents"] == 125000
    assert list(tmp_path.glob(".workspace.json.*.tmp")) == []


@pytest.mark.parametrize("usage", [None, {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40}])
def test_reported_model_usage_is_preserved_without_counting_reused_plans_as_new_calls(tmp_path, monkeypatch, usage):
    calls = []
    class Model:
        def with_structured_output(self, schema, *, include_raw):
            assert schema is Plan and include_raw is True
            return self
        def invoke(self, prompt):
            calls.append(prompt)
            return {"parsed": planned("reconcile_paid")(None), "parsing_error": None,
                    "raw": AIMessage(content="", response_metadata={"model_name": "scripted-response-model"}, usage_metadata=usage)}
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-not-a-provider-key")
    monkeypatch.setenv("OPENAI_MODEL", "scripted-request-model")
    monkeypatch.setattr("revenue_desk.graph.ChatOpenAI", lambda **_kwargs: Model())
    workspace = setup(tmp_path)
    first = run(workspace, model_plan)
    assert first["plan_reused"] is False
    assert first["planning"] == {"source": "model_response", "requested_model": "scripted-request-model",
        "response_model": "scripted-response-model", "usage": usage, "cost_usd": None, "parsed": True}
    restarted = Workspace(workspace.path)
    second = run(restarted, lambda _: pytest.fail("cached plan must not call a model"))
    assert second["plan_reused"] is True
    assert second["planning"] == first["planning"]
    assert len(calls) == len(restarted.data["requests"]["req-1"]["planning_observations"]) == 1


def test_unparseable_model_response_keeps_usage_and_performs_no_business_effect(tmp_path, monkeypatch):
    class Model:
        def with_structured_output(self, _schema, **_kwargs):
            return self
        def invoke(self, _prompt):
            return {"parsed": None, "parsing_error": ValueError("synthetic invalid plan"),
                    "raw": AIMessage(content="unparseable", usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25})}
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-not-a-provider-key")
    monkeypatch.setattr("revenue_desk.graph.ChatOpenAI", lambda **_kwargs: Model())
    workspace = setup(tmp_path)
    with pytest.raises(ValueError, match="valid plan"):
        run(workspace, model_plan)
    record = Workspace(workspace.path).data["requests"]["req-1"]
    assert record["status"] == "planning_failed"
    assert record["planning_observations"][0]["usage"]["total_tokens"] == 25
    assert record["done"] == []
    assert workspace.data["emails"] == workspace.data["slack"] == []
    assert workspace.data["invoices"][0]["credit_cents"] == 0
