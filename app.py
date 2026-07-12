"""
Command-line entry point.

    python app.py data/proposal_low_risk.html
    python app.py data/proposal_disclosure_mismatch.html --controller v2

Prints the final decision.json to stdout and confirms where it (and any
drafted email files) were written on disk.
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the commercial property underwriting workflow.")
    parser.add_argument("file_path", help="Path to a proposal .html or .pdf file (e.g. data/proposal_low_risk.html)")
    parser.add_argument(
        "--controller", choices=["v1", "v2"], default="v1",
        help="v1: workflow/controller.py (hand-rolled Python routing). "
             "v2: workflow/property_controller.py (real google.adk.workflow.Workflow graph).",
    )
    args = parser.parse_args()

    if not os.path.exists(args.file_path):
        print(f"File not found: {args.file_path}", file=sys.stderr)
        sys.exit(1)

    if args.controller == "v2":
        from workflow.property_controller import run_workflow
        decision = run_workflow(args.file_path)
    else:
        from workflow.controller import run_workflow
        from workflow.progress import ProgressTracker
        tracker = ProgressTracker(on_event=lambda e: print(f"[{e['event'].upper():>10}] {e['phase']} :: {e['step']}"))
        decision = run_workflow(args.file_path, tracker=tracker)

    print()
    print(json.dumps(decision, indent=2))
    print()
    print(f"Decision written to output/decision_{(decision.get('application_id') or 'UNKNOWN').replace('/', '_')}.json")
    emails = decision.get("communication", {}).get("emails_generated", 0)
    if emails:
        print(f"{emails} email draft(s) written to output/emails/ (status: DRAFT_NOT_SENT, never sent).")


if __name__ == "__main__":
    main()
