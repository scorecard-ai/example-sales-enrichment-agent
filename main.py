"""
Entry point for the Sales Enrichment Agent Scorecard evaluation.

What this script does
─────────────────────
1. Loads env vars from .env (API keys, OTel config).
2. Sets the OTel environment variables that the claude CLI subprocess needs to
   export traces to Scorecard. These must be in the environment before any
   subprocess is spawned.
3. Defines 5 sample test cases (prospects to enrich).
4. Calls Scorecard's run_and_evaluate(), which:
     a. Creates a Run in Scorecard.
     b. For each test case, generates a UUID `otel_link_id`.
     c. Calls enrich_prospect(inputs, system_version, options) where
        options["otel_link_id"] is that UUID.
     d. enrich_prospect() injects the UUID into the claude CLI subprocess env
        as scorecard.otel_link_id, then runs the agent.
     e. The subprocess exports OTel spans that carry scorecard.otel_link_id.
     f. run_and_evaluate() creates a Scorecard SDK Record with
        otelLinkId=<uuid>, so Scorecard merges the trace into that record.
5. Prints the run URL where you can view results + attached traces.

Trace → Record linking
──────────────────────
    run_and_evaluate()
        │
        ├─ generates otel_link_id = "abc-123-uuid"
        │
        ├─ calls enrich_prospect(inputs, None, {"otel_link_id": "abc-123-uuid"})
        │       │
        │       └─ agent.py: ClaudeAgentOptions(env={
        │              "OTEL_RESOURCE_ATTRIBUTES":
        │                  "scorecard.project_id=...,scorecard.otel_link_id=abc-123-uuid"
        │          })
        │          │
        │          └─ claude CLI subprocess starts, reads OTEL_RESOURCE_ATTRIBUTES,
        │             initialises OTel with scorecard.otel_link_id on every span
        │             │
        │             ├─ span: WebSearch("Databricks news 2025")
        │             ├─ span: crm_lookup(company="Databricks", ...)
        │             ├─ span: linkedin_profile_lookup(full_name="Sarah Chen", ...)
        │             ├─ span: company_intel_lookup(company_name="Databricks")
        │             ├─ span: email_finder(full_name="Sarah Chen", ...)
        │             └─ span: enrichment_score(contact_id="SF-...", ...)
        │
        └─ creates SDK Record with otelLinkId="abc-123-uuid"
           Scorecard backend matches → trace merged into record
"""
import asyncio
import os

from dotenv import load_dotenv
from scorecard_ai import Scorecard
from scorecard_ai.lib import run_and_evaluate, SystemOptions

# ── Load env ──────────────────────────────────────────────────────────────────

load_dotenv()

SCORECARD_API_KEY = os.environ["SCORECARD_API_KEY"]
SCORECARD_PROJECT_ID = os.environ["SCORECARD_PROJECT_ID"]

# SCORECARD_METRIC_IDS is optional — leave blank to capture traces without scoring
_raw_metric_ids = os.environ.get("SCORECARD_METRIC_IDS", "")
METRIC_IDS = [m.strip() for m in _raw_metric_ids.split(",") if m.strip()]

# ── OTel tracing config ───────────────────────────────────────────────────────
# Set these BEFORE importing agent.py or spawning any subprocess.
# The claude CLI subprocess inherits the parent env, so these vars are available
# to the OTel SDK that runs inside each agent invocation.
#
# OTEL_RESOURCE_ATTRIBUTES is intentionally NOT set here — agent.py injects it
# per-run via ClaudeAgentOptions(env=...) to carry the correct otel_link_id.

os.environ.setdefault("BETA_TRACING_ENDPOINT", "https://tracing.scorecard.io/otel")
os.environ.setdefault("OTEL_EXPORTER_OTLP_HEADERS", f"authorization=Bearer {SCORECARD_API_KEY}")
os.environ.setdefault("ENABLE_BETA_TRACING_DETAILED", "1")

# Import after env is configured
from agent import run_enrichment_agent  # noqa: E402

# ── Test cases ────────────────────────────────────────────────────────────────
# Plain dicts satisfying the {inputs, expected} shape expected by run_and_evaluate.
# `expected` is used by Scorecard's LLM-judge metrics; for a traces-only demo
# you can leave it as a descriptive string.

TEST_CASES = [
    {
        "inputs": {
            "name": "Sarah Chen",
            "company": "Databricks",
            "domain": "databricks.com",
            "role_hint": "VP of Engineering",
        },
        "expected": {
            "expected_icp_grade": "A",
            "evaluation_notes": (
                "Databricks is a large, well-funded enterprise data/AI company "
                "(Series H, ~12,000 employees, multi-billion ARR). A VP of Engineering "
                "at this scale is a high-value contact. Email should match @databricks.com. "
                "ICP grade should be A with signals like large headcount, high ARR, strong "
                "engineering org, and active hiring. Web research should surface a specific "
                "2025/2026 Databricks announcement (product launch, acquisition, or funding event)."
            ),
        },
    },
    {
        "inputs": {
            "name": "Marcus Webb",
            "company": "Notion",
            "domain": "notion.so",
            "role_hint": "Co-Founder & CTO",
        },
        "expected": {
            "expected_icp_grade": "A",
            "evaluation_notes": (
                "Notion is a well-known Series C+ productivity SaaS company with thousands "
                "of employees and high ARR. A Co-Founder and CTO is a top-tier contact. "
                "Email should match @notion.so. ICP grade should be A given company scale "
                "and technical leadership seniority. Web research should cite a specific "
                "Notion product update, partnership, or funding news from 2025 or 2026."
            ),
        },
    },
    {
        "inputs": {
            "name": "Priya Nair",
            "company": "Zendesk",
            "domain": "zendesk.com",
            "role_hint": "Customer Success Manager",
        },
        "expected": {
            "expected_icp_grade": "B",
            "evaluation_notes": (
                "Zendesk is a large established SaaS company (acquired by private equity "
                "in 2022, ~6,000 employees). However, a Customer Success Manager is a "
                "mid-level individual contributor, not a decision maker, which limits ICP "
                "grade. Grade should be B — strong company but lower seniority contact. "
                "Email should match @zendesk.com. Web research should mention Zendesk-specific "
                "news (product update, AI feature, or organizational change) from 2025 or 2026."
            ),
        },
    },
    {
        "inputs": {
            "name": "Alex Rivera",
            "company": "Acme Widgets",
            "domain": "acmewidgets.io",
            "role_hint": "unknown",
        },
        "expected": {
            "expected_icp_grade": "C",
            "evaluation_notes": (
                "Acme Widgets is a fictional/placeholder company with no real online presence. "
                "Expect low headcount, low ARR, early funding stage or unknown. Role is unknown, "
                "limiting seniority assessment. ICP grade should be C. CRM lookup will likely "
                "return not-found. Web research will likely return little or no useful results — "
                "the summary should honestly reflect the lack of findable information rather than "
                "fabricating facts."
            ),
        },
    },
    {
        "inputs": {
            "name": "Jordan Kim",
            "company": "Salesforce",
            "domain": "salesforce.com",
            "role_hint": "Director of Sales Operations",
        },
        "expected": {
            "expected_icp_grade": "A",
            "evaluation_notes": (
                "Salesforce is one of the largest enterprise SaaS companies globally "
                "(~70,000 employees, multi-billion ARR). A Director of Sales Operations "
                "is a senior decision-maker in the target persona. ICP grade should be A "
                "with strong signals: massive headcount, very high ARR, mature tech stack. "
                "Email should match @salesforce.com. Web research should surface a specific "
                "Salesforce announcement from 2025 or 2026 (Agentforce updates, earnings, "
                "acquisitions, or product releases)."
            ),
        },
    },
]


# ── System function ───────────────────────────────────────────────────────────

def enrich_prospect(inputs: dict, system_version, options: SystemOptions) -> dict:
    """
    Called by run_and_evaluate() for each test case.

    Receives a unique otel_link_id in `options` that must be propagated to
    the Claude Agent SDK subprocess so Scorecard can link the trace to this
    SDK record.

    We use asyncio.run() as the sync→async bridge because run_and_evaluate()
    is synchronous and each test case runs sequentially, so creating a fresh
    event loop per call is safe.
    """
    otel_link_id = options["otel_link_id"]
    print(
        f"  → Enriching {inputs['name']!r} at {inputs.get('company', '?')!r} "
        f"  [trace: {otel_link_id[:8]}…]"
    )
    return asyncio.run(run_enrichment_agent(inputs, otel_link_id))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("Sales Enrichment Agent — Scorecard Evaluation")
    print("=" * 56)
    print(f"  Project ID  : {SCORECARD_PROJECT_ID}")
    print(f"  Test cases  : {len(TEST_CASES)}")
    print(f"  Metrics     : {', '.join(METRIC_IDS) if METRIC_IDS else '(none — traces only)'}")
    print(f"  Trace ingest: https://tracing.scorecard.io")
    print()

    scorecard_client = Scorecard(api_key=SCORECARD_API_KEY)

    run_response = run_and_evaluate(
        client=scorecard_client,
        project_id=SCORECARD_PROJECT_ID,
        metric_ids=METRIC_IDS,
        testcases=TEST_CASES,
        system=enrich_prospect,
    )

    print()
    print("✓  Evaluation complete!")
    print(f"   Run ID   : {run_response['id']}")
    print(f"   View at  : {run_response['url']}")
    print()
    print("Traces are being exported to Scorecard (allow 1–2 min to appear).")
    print("On the Records page you will see:")
    print("  • Conversation view — full chat replay per enrichment run")
    print("  • Timeline view     — Gantt chart of all tool call spans")
    print("  • Full trace view   — every LLM call with tokens, latency, inputs/outputs")
    print()


if __name__ == "__main__":
    main()
