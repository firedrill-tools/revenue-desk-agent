import argparse
import json
from pathlib import Path
from .graph import build_graph
from .workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description="Reconcile a revenue desk request")
    parser.add_argument("request_id")
    parser.add_argument("invoice_id")
    parser.add_argument("request")
    parser.add_argument("--approved-credit-cents", type=int, default=0)
    parser.add_argument("--workspace", type=Path, default=Path("workspace.json"))
    args = parser.parse_args()
    if not args.workspace.exists():
        parser.error("workspace missing; copy fixtures/starter.json first")
    workspace = Workspace(args.workspace)
    try:
        result = build_graph(workspace).invoke({"request_id": args.request_id, "invoice_id": args.invoice_id,
                                                "request": args.request,
                                                "approved_credit_cents": args.approved_credit_cents})
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result["result"], indent=2))


if __name__ == "__main__":
    main()
