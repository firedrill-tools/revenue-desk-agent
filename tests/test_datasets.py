from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil

import pytest
from revenue_desk import cli
from revenue_desk.datasets import fixture_root, initialize_case, load_cases
from revenue_desk.graph import Plan, build_graph
from revenue_desk.workspace import Workspace


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)


def test_model_free_list_and_generator_reproduce_all_bytes(tmp_path,capsys):
    spec=importlib.util.spec_from_file_location("generator",Path(__file__).parents[1]/"scripts/build_fixtures.py")
    generator=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generator.build(tmp_path)
    for path in fixture_root().glob("*.json"):
        assert path.read_bytes() == (tmp_path/path.name).read_bytes()
    assert cli.main(["--list-cases"]) == 0
    listed=json.loads(capsys.readouterr().out)
    assert listed["version"] == "2.0.0" and listed["case_count"] == 10
    assert {entry["profile"] for entry in listed["cases"]} == {"starter","busy","ambiguous","boundary"}


@pytest.mark.parametrize("case",load_cases(),ids=lambda entry:entry["case_id"])
def test_selected_cases_keep_unrelated_state_and_enforce_policy_boundaries(tmp_path,case):
    path=tmp_path/"workspace.json"
    initialized=initialize_case(case["case_id"],path)
    assert path.read_bytes() == case["bytes"] and initialized["model_called"] is False
    assert path.stat().st_mode & 0o777 == 0o600
    workspace=Workspace(path)
    original=deepcopy(workspace.data)
    calls=[]
    def planner(state):
        calls.append(state)
        intent = "credit" if case["case_id"] in {"approved-credit","busy-credit","unapproved-credit","hostile-note"} else "reconcile_paid"
        return Plan(intent=intent,rationale="Controlled offline planning decision",email_body="Controlled offline factual confirmation.",
                    requested_slot="2026-10-20T14:00:00Z" if case["case_id"] == "no-slots" else None)
    result=build_graph(workspace,planner).invoke(case["task"])["result"]
    if case["case_id"] == "prior-complete":
        assert calls == [] and result["replayed"] and path.read_bytes() == case["bytes"]
        assert result["planning"]["source"] == "synthetic_fixture_history" and result["planning"]["usage"] is None
    else:
        assert len(calls) == 1 and result["dataset"]["case_id"] == case["case_id"]
        assert result["initial_state_sha256"] == case["sha256"]
        if case["case_id"] in {"payment-claim","unapproved-credit","hostile-note"}:
            assert result["intent"] == "review" and workspace.data["emails"] == original["emails"]
            assert workspace.data["invoices"] == original["invoices"]
        if case["case_id"] == "no-slots":
            assert workspace.data["meetings"] == original["meetings"]
        selected=next(i for i in original["invoices"] if i["id"] == case["task"]["invoice_id"])
        for invoice in original["invoices"]:
            if invoice["id"] != selected["id"]:
                assert invoice in workspace.data["invoices"]
        for account in original["accounts"]:
            if account["id"] != selected["account_id"]:
                assert account in workspace.data["accounts"]
        for key in ("emails","slack","meetings"):
            assert workspace.data[key][:len(original[key])] == original[key]
        before=path.read_bytes()
        replay=build_graph(workspace,lambda _:pytest.fail("completed replay cannot plan")).invoke(case["task"])["result"]
        assert replay["replayed"] and path.read_bytes() == before


@pytest.mark.parametrize("fault",["drift","escape","duplicate","relationship"])
def test_dataset_refuses_drift_escape_and_incoherent_state_before_initialization(tmp_path,fault):
    root=tmp_path/"fixtures";shutil.copytree(fixture_root(),root)
    manifest=json.loads((root/"manifest.json").read_text())
    entry=manifest["cases"][0]
    path=root/entry["workspace"]
    if fault == "drift":path.write_text("{}")
    elif fault == "escape":
        outside=tmp_path/"outside.json";outside.write_bytes(path.read_bytes());path.unlink();path.symlink_to(outside)
    elif fault == "duplicate":manifest["cases"][1]["case_id"]=entry["case_id"]
    else:
        state=json.loads(path.read_text());state["invoices"][0]["account_id"]="unknown"
        raw=json.dumps(state).encode();path.write_bytes(raw);entry["sha256"]=sha256(raw).hexdigest()
    (root/"manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):initialize_case("starter",tmp_path/"output.json",root=root)
    assert not (tmp_path/"output.json").exists()


def test_initialization_never_overwrites_and_cli_requires_a_fresh_destination(tmp_path,capsys):
    path=tmp_path/"state.json"
    assert cli.main(["--init-case","busy","--workspace",str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["reset_coverage"] == "local_json_only"
    original=path.read_bytes()
    with pytest.raises(FileExistsError):initialize_case("starter",path)
    assert path.read_bytes() == original
    with pytest.raises(SystemExit) as error:cli.main(["--init-case","starter"])
    assert error.value.code == 2


@pytest.mark.parametrize("fault",["duplicate_invoice","fractional_amount","orphan_credit"])
def test_bad_live_workspace_ledger_cannot_reach_planner(tmp_path,fault):
    state=json.loads((fixture_root()/"starter.json").read_text())
    if fault == "duplicate_invoice":state["invoices"].append(state["invoices"][0].copy())
    elif fault == "fractional_amount":state["invoices"][0]["paid_cents"]=1.5
    else:state["invoices"][0]["credit_request_ids"]=["unrelated-credit"]
    path=tmp_path/"state.json";path.write_text(json.dumps(state))
    with pytest.raises(ValueError):Workspace(path)
