"""
CI entry point for Scorecard GitHub Actions dispatch.

Unlike `main.py` (which runs five hardcoded sample prospects), this script is
driven entirely by environment variables supplied by the GitHub workflow. It is
what `.github/workflows/scorecard-eval.yml` runs when Scorecard dispatches an
evaluation (either via the "Kickoff Run" page's GitHub integration, which sends
a `repository_dispatch: start-evaluation` event, or via a manual
`workflow_dispatch`).

It pulls the testcases from a real Scorecard Testset (by `TESTSET_ID`) and runs
each one through the same Claude Agent SDK agent used by the rest of the repo
(`agent.run_enrichment_agent`), so the dispatched run is a faithful end-to-end
exercise of the agent.

Required env (set by the workflow):
  SCORECARD_API_KEY   Scorecard org API key (GitHub secret)
  ANTHROPIC_API_KEY   Anthropic key for the agent (GitHub secret; read by the SDK)
  PROJECT_ID          Scorecard project id
  TESTSET_ID          Scorecard testset id to evaluate
  METRIC_IDS          Comma-separated metric ids (may be empty for traces-only)
  SYSTEM_VERSION_ID   Optional system version id

The Testset's input fields should match what the agent expects: either a
free-form `query` string, or structured `name` / `company` / `domain` /
`role_hint` fields.
"""
import asyncio
import os
import re


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


# Read config from the env the workflow injects. Resolve everything BEFORE
# importing `agent`, because agent.py spawns the claude CLI subprocess and reads
# the OTel env vars below to link trace spans back to each Scorecard record.
SCORECARD_API_KEY = _require("SCORECARD_API_KEY")
PROJECT_ID = _require("PROJECT_ID")
TESTSET_ID = _require("TESTSET_ID")
METRIC_IDS = re.findall(r"\b\d+\b", os.environ.get("METRIC_IDS", ""))
SYSTEM_VERSION_ID = os.environ.get("SYSTEM_VERSION_ID") or None

# agent.py reads SCORECARD_PROJECT_ID to stamp scorecard.project_id on spans.
os.environ.setdefault("SCORECARD_PROJECT_ID", PROJECT_ID)
os.environ.setdefault("BETA_TRACING_ENDPOINT", "https://tracing.scorecard.io/otel")
os.environ.setdefault(
    "OTEL_EXPORTER_OTLP_HEADERS", f"authorization=Bearer {SCORECARD_API_KEY}"
)
os.environ.setdefault("ENABLE_BETA_TRACING_DETAILED", "1")

from scorecard_ai import Scorecard  # noqa: E402
from scorecard_ai.lib import run_and_evaluate, SystemOptions  # noqa: E402

from agent import run_enrichment_agent  # noqa: E402


def enrich_prospect(inputs: dict, system_version, options: SystemOptions) -> dict:
    """System function called by run_and_evaluate() for each testcase."""
    otel_link_id = options["otel_link_id"]
    label = inputs.get("query") or inputs.get("name") or "prospect"
    print(f"  → Enriching {label!r}  [trace: {otel_link_id[:8]}…]")
    return asyncio.run(run_enrichment_agent(inputs, otel_link_id))


def main() -> None:
    print()
    print("Sales Enrichment Agent — Scorecard CI Evaluation")
    print("=" * 56)
    print(f"  Project ID : {PROJECT_ID}")
    print(f"  Testset ID : {TESTSET_ID}")
    print(f"  Metrics    : {', '.join(METRIC_IDS) if METRIC_IDS else '(none — traces only)'}")
    print(f"  System ver : {SYSTEM_VERSION_ID or '(none)'}")
    print()

    client = Scorecard(api_key=SCORECARD_API_KEY)

    run_response = run_and_evaluate(
        client=client,
        project_id=PROJECT_ID,
        testset_id=TESTSET_ID,
        metric_ids=METRIC_IDS,
        system=enrich_prospect,
        **({"system_version_id": SYSTEM_VERSION_ID} if SYSTEM_VERSION_ID else {}),
    )

    print()
    print("✓  Evaluation complete!")
    print(f"   Run ID  : {run_response['id']}")
    print(f"   View at : {run_response['url']}")
    print()


if __name__ == "__main__":
    main()
