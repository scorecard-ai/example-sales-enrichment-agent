"""
Entry point for the Scorecard GitHub Actions workflow.

Dispatched by Scorecard via workflow_dispatch (or repository_dispatch with the
`start-evaluation` event). The workflow passes the evaluation config as env
vars: PROJECT_ID, TESTSET_ID, METRIC_IDS, and optionally SYSTEM_VERSION_ID.

Unlike main.py (which defines its own inline test cases), this script runs
every Testcase in the Testset selected in the Scorecard UI.

By default it uses a fast deterministic stub system so CI runs are quick and
don't require an Anthropic key. Set USE_REAL_AGENT=1 (with ANTHROPIC_API_KEY
configured) to run the real Claude Agent SDK enrichment agent instead.
"""
import json
import os
import re
from typing import Any

from scorecard_ai import Scorecard
from scorecard_ai.lib import run_and_evaluate, SystemOptions


def enrich_prospect_stub(
    inputs: dict[str, Any], system_version: Any, options: SystemOptions
) -> dict:
    """
    Deterministic stand-in for the real enrichment agent.

    Returns the same JSON shape the agent produces so LLM-judge metrics have
    something structured to score, without spawning the Claude CLI subprocess.
    """
    name = inputs.get("name") or str(inputs)
    company = inputs.get("company")
    return {
        "response": json.dumps(
            {
                "prospect": {
                    "name": name,
                    "company": company,
                    "role": inputs.get("role"),
                },
                "summary": (
                    f"Stub enrichment for {name}"
                    + (f" at {company}" if company else "")
                    + ". Run with USE_REAL_AGENT=1 for a real agent run."
                ),
                "fit_score": 50,
                "recommended_action": "review manually",
            }
        ),
    }


def get_system():
    if os.environ.get("USE_REAL_AGENT") == "1":
        # Imported lazily: main.py pulls in the Claude Agent SDK, which needs
        # the claude CLI and ANTHROPIC_API_KEY — only required in agent mode.
        from main import enrich_prospect

        return enrich_prospect
    return enrich_prospect_stub


def main() -> None:
    project_id = os.environ["PROJECT_ID"]
    testset_id = os.environ["TESTSET_ID"]
    metric_ids = re.findall(r"\b\d+\b", os.environ["METRIC_IDS"])
    system_version_id = os.environ.get("SYSTEM_VERSION_ID") or None

    print("Sales Enrichment Agent — Scorecard CI Evaluation")
    print(f"  Project ID : {project_id}")
    print(f"  Testset ID : {testset_id}")
    print(f"  Metrics    : {', '.join(metric_ids) or '(none)'}")
    print(f"  System     : {'real agent' if os.environ.get('USE_REAL_AGENT') == '1' else 'stub'}")

    client = Scorecard(api_key=os.environ["SCORECARD_API_KEY"])

    run = run_and_evaluate(
        client=client,
        project_id=project_id,
        testset_id=testset_id,
        metric_ids=metric_ids,
        **({"system_version_id": system_version_id} if system_version_id else {}),
        system=get_system(),
    )

    print()
    print("✓  Evaluation complete!")
    print(f"   Run ID  : {run['id']}")
    print(f"   View at : {run['url']}")


if __name__ == "__main__":
    main()
