"""
Entry point.

Usage:
    python app.py data/proposal.html
    python app.py path/to/proposal.pdf

Runs the full underwriting workflow end-to-end (Google ADK LlmAgents +
custom workflow controller) and prints the final decision. All artifacts
(decision.json, and any email_draft_*.json) are written to output/.

Requires a model provider + API key set as environment variables --
see workflow/model_config.py for details.
"""

import sys
import json

from workflow.controller import run_workflow


def main():
    if len(sys.argv) < 2:
        print("Usage: python app.py <path-to-proposal-file>")
        sys.exit(1)

    file_path = sys.argv[1]
    decision = run_workflow(file_path)

    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
