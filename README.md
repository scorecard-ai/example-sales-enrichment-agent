# Sales Enrichment Agent

A B2B sales enrichment agent built with the [Claude Agent SDK](https://docs.anthropic.com/claude/docs/agents) and evaluated with [Scorecard](https://scorecard.io).

The agent takes a prospect's name, company, domain, and role hint, then calls six tools in sequence — web search, CRM lookup, LinkedIn profile, company intel, email finder, and ICP scoring — and returns a structured enrichment report.

This repo is used as the example project in Scorecard. When a new Scorecard org is created, pre-built traces from this agent are seeded into the example project so you can explore conversation views, tool call timelines, and LLM-judge scores immediately.

## How it works

```
main.py  →  run_and_evaluate()  →  enrich_prospect()  →  agent.py
```

- **`main.py`** — defines five sample prospects and calls Scorecard's `run_and_evaluate()`, which creates a Run and calls `enrich_prospect()` for each test case.
- **`agent.py`** — runs the Claude agent via `ClaudeSDKClient`. Injects `scorecard.otel_link_id` into the subprocess env so Scorecard can link OTel trace spans to the corresponding SDK record.
- **`tools.py`** — five simulated internal tools served over MCP: `crm_lookup`, `linkedin_profile_lookup`, `company_intel_lookup`, `email_finder`, `enrichment_score`. The agent also has access to the real `WebSearch` built-in tool.

Each run produces a Scorecard record with:
- Full conversation replay (all turns with the agent)
- Tool call timeline (Gantt chart of every span)
- LLM-judge scores for ICP grade accuracy, data completeness, and web research quality

## Setup

**Prerequisites:** Python 3.11+, `pip`, a Scorecard account, and an Anthropic API key.

```bash
git clone https://github.com/scorecard-ai/example-sales-enrichment-agent.git
cd example-sales-enrichment-agent
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your keys:

```
ANTHROPIC_API_KEY=sk-ant-...
SCORECARD_API_KEY=ak_...
SCORECARD_PROJECT_ID=<your project ID>
SCORECARD_METRIC_IDS=<comma-separated metric IDs>   # optional
```

Your `SCORECARD_PROJECT_ID` and `SCORECARD_METRIC_IDS` are in your Scorecard project settings. To run without scoring (traces only), leave `SCORECARD_METRIC_IDS` empty.

## Run

```bash
python main.py
```

The script will print a run URL where you can view results and traces:

```
Sales Enrichment Agent — Scorecard Evaluation
========================================================
  Project ID  : 1234
  Test cases  : 5
  Metrics     : 456, 789
  Trace ingest: https://tracing.scorecard.io

  → Enriching 'Sarah Chen' at 'Databricks'  [trace: abc12345…]
  → Enriching 'Marcus Webb' at 'Notion'     [trace: def67890…]
  ...

✓  Evaluation complete!
   Run ID   : 99999
   View at  : https://app.scorecard.io/projects/1234/runs/99999
```

Allow 1–2 minutes for traces to appear in the Scorecard UI.

## Metrics

Three LLM-judge metrics are used to evaluate each enrichment:

| Metric | What it checks |
|---|---|
| **ICP Grade Accuracy** | Does the A/B/C grade match the expected grade and is it supported by the listed signals? |
| **Enrichment Data Completeness** | Are all fields populated with non-null, non-placeholder values? |
| **Web Research Quality** | Does the `web_research_summary` contain specific, verifiable facts rather than generic filler? |

Each metric scores 1–5. A score of 4 or above is passing.
