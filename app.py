"""
Entry point.

Usage:
    python app.py data/proposal.html                 # v1: hand-rolled Python controller
    python app.py data/proposal.html --v2             # v2: real ADK Workflow graph
    python app.py path/to/proposal.pdf

Runs the full underwriting workflow end-to-end (Google ADK LlmAgents) and
prints the final decision. All artifacts (decision.json, and any
email_draft_*.json) are written to output/.

Requires a model provider + API key set as environment variables --
see workflow/model_config.py for details.
"""

import sys
import json
from dotenv import load_dotenv

load_dotenv()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_v2 = "--v2" in sys.argv

    if not args:
        print("Usage: python app.py <path-to-proposal-file> [--v2]")
        sys.exit(1)

    file_path = args[0]

    if use_v2:
        from workflow.adk_controller import run_workflow
    else:
        from workflow.controller import run_workflow

    decision = run_workflow(file_path)

    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
