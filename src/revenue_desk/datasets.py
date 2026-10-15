"""Model-free, digest-bound selection and private exclusive initialization."""
from hashlib import sha256
import json
import os
from pathlib import Path
from .contracts import WorkspaceData

DATASET, VERSION = "synthetic-revenue-desk", "2.0.0"
PROFILES = {"starter", "busy", "ambiguous", "boundary"}


def fixture_root():
    bundled = Path(__file__).parent / "sample_data"
    return bundled if bundled.is_dir() else Path(__file__).resolve().parents[2] / "fixtures"


def bounded(path, limit):
    with path.open("rb") as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError("Dataset file too large")
    return raw


def load_cases(root=None):
    root = Path(root or fixture_root()).resolve()
    manifest_path = (root/"manifest.json").resolve()
    if not manifest_path.is_relative_to(root):
        raise ValueError("Manifest escapes dataset root")
    manifest = json.loads(bounded(manifest_path,128*1024))
    if (manifest.get("dataset"),manifest.get("version")) != (DATASET,VERSION):
        raise ValueError("Unqualified dataset identity/version")
    entries = manifest.get("cases")
    if not isinstance(entries,list) or not 1 <= len(entries) <= 100:
        raise ValueError("Dataset requires 1–100 cases")
    result, seen = [], set()
    for entry in entries:
        case_id, profile = entry["case_id"],entry["profile"]
        if not isinstance(case_id,str) or not case_id or case_id in seen or profile not in PROFILES:
            raise ValueError("Duplicate identity/unknown profile")
        seen.add(case_id)
        relative = Path(entry["workspace"])
        path = (root/relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root):
            raise ValueError("Workspace escapes dataset root")
        raw = bounded(path,512*1024)
        if sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("Workspace digest drift")
        state = json.loads(raw)
        parsed = WorkspaceData.model_validate(state)
        if state.get("dataset") != {"id":DATASET,"version":VERSION,"profile":profile,"case_id":case_id}:
            raise ValueError("Embedded dataset identity differs from manifest")
        from .graph import Request
        task = Request.model_validate(entry["task"])
        if not any(invoice.id == task.invoice_id for invoice in parsed.invoices):
            raise ValueError("Case selects an unknown invoice")
        if profile == "busy" and (len(parsed.accounts)<12 or len(parsed.invoices)<23 or len(parsed.requests)<2):
            raise ValueError("Busy profile requires population and prior work")
        result.append({**entry,"bytes":raw})
    if {entry["profile"] for entry in result} != PROFILES:
        raise ValueError("All four profiles are required")
    return result


def list_cases(root=None):
    cases = load_cases(root)
    return {"dataset":DATASET,"version":VERSION,"case_count":len(cases),"cases":[{key:value for key,value in entry.items() if key != "bytes"} for entry in cases]}


def initialize_case(case_id, path, *, root=None):
    case = next((case for case in load_cases(root) if case["case_id"] == case_id),None)
    if case is None:
        raise ValueError(f"Unknown case: {case_id}")
    path = Path(path).absolute()
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(descriptor,"wb") as stream:
            stream.write(case["bytes"])
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"dataset":DATASET,"version":VERSION,"case_id":case_id,"workspace":str(path),"sha256":case["sha256"],
            "task":case["task"],"reset_coverage":"local_json_only","model_called":False}
