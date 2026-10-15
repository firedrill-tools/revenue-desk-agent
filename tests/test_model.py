"""Real LangGraph -> LangChain -> OpenAI JSON-schema HTTP, no paid calls."""
import asyncio
from copy import deepcopy
from functools import partial
import json

import httpx2
import pytest
from revenue_desk import model
from revenue_desk.model import model_plan
from test_graph import FIXTURE, run, setup

PLAN = {"intent": "reconcile_paid", "rationale": "The selected invoice is paid; the separate account invoice is still outstanding.",
        "email_body": "Invoice 410 is paid. The separate invoice 412 still has a 425.00 balance.", "requested_slot": "2026-10-20T14:00:00Z"}
USAGE = {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60,
         "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 4}}


def response(*, plan=PLAN, finish="stop", usage=USAGE, message=None):
    body = {"id": "chatcmpl_synthetic", "object": "chat.completion", "created": 1792098000, "model": "gpt-6.1-sol-synthetic",
            "choices": [{"index": 0, "finish_reason": finish, "message": message or {"role": "assistant", "content": json.dumps(plan)}}]}
    if usage is not None:
        body["usage"] = usage
    return body


class Script(httpx2.MockTransport):
    def __init__(self, replies):
        self.replies, self.requests, self.closed = replies, [], False
        super().__init__(self.handle)
    def handle(self, request):
        self.requests.append(request)
        reply = self.replies[len(self.requests) - 1]
        return reply if isinstance(reply, httpx2.Response) else httpx2.Response(200, json=deepcopy(reply), headers={"x-request-id": "req_synthetic"})
    def close(self):
        self.closed = True
        super().close()


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    for key in ("OPENAI_BASE_URL", "OPENAI_API_BASE"):
        monkeypatch.delenv(key, raising=False)


def test_actual_graph_structured_planner_commits_all_systems_and_replay_retains_original_evidence(tmp_path):
    workspace = setup(tmp_path, FIXTURE.with_name("busy.json"))
    original = deepcopy(workspace.data)
    script = Script([response()])
    result = run(workspace, partial(model_plan, transport=script))
    assert len(script.requests) == 1 and script.closed
    request = script.requests[0]
    assert request.method == "POST" and str(request.url) == "https://api.openai.com/v1/chat/completions"
    body = json.loads(request.content)
    assert body["store"] is False and body["stream"] is False
    assert body["max_completion_tokens"] == 4096
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    prompt = body["messages"][0]["content"]
    assert '"accounting_balance_cents": 42500' in prompt and '"inv-412"' in prompt
    assert "synthetic-revenue-desk" not in prompt and "planning_observations" not in prompt
    evidence = result["planning"]
    assert evidence["source"] == "langchain-openai-sdk" and evidence["parsed"]
    assert evidence["response_model"] == "gpt-6.1-sol-synthetic"
    assert evidence["responses"][0]["reported_usage"] == USAGE
    assert evidence["usage"] == {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60} and evidence["cost_usd"] is None
    assert workspace.data["accounts"][0]["crm_balance_cents"] == 42500
    for key in ("emails", "slack", "meetings"):
        assert workspace.data[key][:-1] == original[key]
        assert workspace.data[key][-1]["request_id"] == "req-1"
    assert workspace.data["invoices"] == original["invoices"]
    assert workspace.data["accounts"][1:] == original["accounts"][1:]
    before = workspace.path.read_bytes()
    replay = run(workspace, lambda _: pytest.fail("must reuse stored plan"))
    assert replay["planning"] == evidence and replay["plan_reused"] and replay["replayed"]
    assert workspace.path.read_bytes() == before


@pytest.mark.parametrize("body", [response(finish="length"), response(finish="content_filter"),
    response(message={"role":"assistant", "content":None,"refusal":"Controlled refusal"}), response(plan={**PLAN,"intent":"other"}),
    response(plan={**PLAN,"email_body":" "*10}), response(plan={**PLAN,"unknown":True}),
    response(message={"role":"assistant","content":"not JSON"})])
def test_rejected_native_output_preserves_raw_usage_in_journal_without_business_effects(tmp_path, body):
    workspace = setup(tmp_path)
    script = Script([body])
    with pytest.raises(ValueError, match="valid plan"):
        run(workspace, partial(model_plan, transport=script))
    record = workspace.data["requests"]["req-1"]
    assert len(script.requests) == 1 and script.closed
    assert record["status"] == "planning_failed" and record["done"] == []
    observation = record["planning_observations"][0]
    assert not observation["parsed"] and observation["responses"][0]["choices"] == body["choices"]
    assert observation["responses"][0]["reported_usage"] == USAGE
    assert observation["usage"]["total_tokens"] == 60
    assert workspace.data["emails"] == workspace.data["slack"] == []


@pytest.mark.parametrize("usage,complete", [(None,False), ({},False), ({"prompt_tokens":40},False),
    ({"prompt_tokens":0,"completion_tokens":0,"total_tokens":0},True)])
def test_absent_partial_and_zero_wire_usage_remain_distinct(tmp_path, usage, complete):
    workspace = setup(tmp_path)
    result = run(workspace, partial(model_plan, transport=Script([response(usage=usage)])))
    evidence = result["planning"]
    assert evidence["responses"][0]["reported_usage"] == usage and evidence["usage_complete"] is complete
    assert (evidence["usage"] is not None) is complete and evidence["cost_usd"] is None


def test_provider_failure_has_no_hidden_retry_and_explicit_retry_keeps_both_observations(tmp_path):
    workspace = setup(tmp_path)
    script = Script([httpx2.Response(503,json={"error":{"message":"controlled outage","type":"server_error"}})])
    with pytest.raises(ValueError, match="valid plan"):
        run(workspace, partial(model_plan, transport=script))
    record = workspace.data["requests"]["req-1"]
    assert len(script.requests) == 1 and script.closed and record["planning_observations"][0]["usage"] is None
    assert record["planning_observations"][0]["responses"][0]["http_status"] == 503
    assert record["planning_observations"][0]["responses"][0]["error"]["type"] == "server_error"
    result = run(workspace, partial(model_plan, transport=Script([response()])))
    assert result["intent"] == "reconcile_paid"
    assert len(workspace.data["requests"]["req-1"]["planning_observations"]) == 2


@pytest.mark.parametrize("failure", [False,True])
def test_owned_async_and_sync_clients_close_on_both_outcomes_and_async_host_is_supported(tmp_path, monkeypatch, failure):
    actual = model.AsyncOpenAI
    async_clients = []
    def create(**kwargs):
        client = actual(**kwargs)
        async_clients.append(client)
        return client
    monkeypatch.setattr(model, "AsyncOpenAI", create)
    workspace = setup(tmp_path)
    state = {"request":"Reconcile paid invoice", "approved_credit_cents":0,"context":workspace.context("inv-410")}
    script = Script([response(finish="length" if failure else "stop")])
    async def host():
        return model_plan(state, transport=script)
    outcome = asyncio.run(host())
    assert (outcome.plan is None) is failure
    assert async_clients[0].is_closed() and script.closed


@pytest.mark.parametrize("failure",[False,True])
def test_cli_only_prints_completed_json_and_keeps_failed_evidence_in_journal(tmp_path,monkeypatch,capsys,failure):
    from revenue_desk import cli
    workspace=setup(tmp_path)
    script=Script([response(finish="length" if failure else "stop")])
    actual=model._plan
    monkeypatch.setattr(model,"_plan",lambda state,**kwargs:actual(state,**{**kwargs,"transport":script}))
    args=["req-cli","inv-410","Reconcile the paid invoice","--workspace",str(workspace.path)]
    if failure:
        with pytest.raises(SystemExit) as error:cli.main(args)
        assert error.value.code == 2
        captured=capsys.readouterr()
        assert captured.out == "" and "valid plan" in captured.err
        record=json.loads(workspace.path.read_text())["requests"]["req-cli"]
        assert record["planning_observations"][0]["responses"][0]["reported_usage"] == USAGE
        assert record["done"] == []
    else:
        assert cli.main(args) == 0
        result=json.loads(capsys.readouterr().out)
        assert result["request_id"] == "req-cli" and result["planning"]["source"] == "langchain-openai-sdk"
    assert script.closed and len(script.requests) == 1
