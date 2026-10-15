import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reconcile a revenue desk request")
    parser.add_argument("request_id",nargs="?")
    parser.add_argument("invoice_id",nargs="?")
    parser.add_argument("request",nargs="?")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--list-cases",action="store_true")
    selection.add_argument("--init-case",metavar="CASE")
    parser.add_argument("--approved-credit-cents", type=int, default=0)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args(argv)
    if args.list_cases or args.init_case:
        if any(value is not None for value in (args.request_id,args.invoice_id,args.request)) or args.approved_credit_cents:
            parser.error("case listing/initialization cannot execute a request")
        if args.init_case and args.workspace is None:
            parser.error("--init-case requires --workspace with a fresh path")
        from .datasets import initialize_case,list_cases
        try:
            print(json.dumps(list_cases() if args.list_cases else initialize_case(args.init_case,args.workspace)))
        except (ValueError,OSError,KeyError) as error:
            parser.error(str(error))
        return 0
    if any(value is None for value in (args.request_id,args.invoice_id,args.request)):
        parser.error("request_id, invoice_id and request are required")
    args.workspace = args.workspace or Path("workspace.json")
    if not args.workspace.exists():
        parser.error("workspace missing; use --init-case starter --workspace NEW_PATH first")
    from .graph import build_graph
    from .workspace import Workspace
    try:
        workspace = Workspace(args.workspace)
        result = build_graph(workspace).invoke({"request_id": args.request_id, "invoice_id": args.invoice_id,
                                                "request": args.request,
                                                "approved_credit_cents": args.approved_credit_cents})
    except (RuntimeError, ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result["result"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
