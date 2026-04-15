# Sales Enrichment Agent

A B2B sales enrichment agent built with the [Claude Agent SDK](https://docs.anthropic.com/claude/docs/agents) and evaluated with [Scorecard](https://scorecard.io).

The agent accepts a free-form query (e.g. "Research Darius Emrani") or structured prospect fields, then calls six tools in sequence — web search, CRM lookup, LinkedIn profile, company intel, email finder, and ICP scoring — and returns a structured enrichment report.

This repo is used as the example project in Scorecard. When a new Scorecard org is created, pre-built traces from this agent are seeded into the example project so you can explore conversation views, tool call timelines, and LLM-judge scores immediately.

## How it works

```
app.py  →  /enrich  →  agent.py  →  tools.py (MCP)
main.py →  run_and_evaluate()  →  agent.py  →  tools.py (MCP)
```

- **`app.py`** — FastAPI web server with a minimal search UI. Accepts a free-form query string and calls the agent.
- **`main.py`** — Batch evaluation mode. Defines five sample prospects and calls Scorecard's `run_and_evaluate()` for each.
- **`agent.py`** — Runs the Claude agent via `ClaudeSDKClient`. Parses free-form or structured input, injects `scorecard.otel_link_id` into the subprocess env so Scorecard can link OTel trace spans to the corresponding SDK record.
- **`tools.py`** — Five simulated internal tools served over MCP: `crm_lookup`, `linkedin_profile_lookup`, `company_intel_lookup`, `email_finder`, `enrichment_score`. The agent also has access to the real `WebSearch` built-in tool.

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

**Web UI** — interactive browser interface:

```bash
uvicorn app:app --reload --port 8000
```

Then open `http://localhost:8000` and type any free-form query into the search bar, e.g. `"Research Darius Emrani"` or `"Sarah Chen, VP Eng at Databricks"`.

**Batch evaluation** — runs five sample prospects through Scorecard:

```bash
python main.py
```

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

## Demo: database version switching

`tools.py` ships with two hardcoded fixture sets for the prospect **Darius Emrani / Scorecard**, controlled by `SALES_DB_VERSION` in `.env`:

| | `v1` (default — stale) | `v2` (corrected) |
|---|---|---|
| LinkedIn seniority | Senior IC | C-Level / Founder |
| Headcount | 8 | 85 |
| ARR estimate | $0 | $12M |
| ICP signals | 0 | 4 |
| **Grade** | **C** | **A** |

The score is computed by the `enrichment_score` tool from the data returned by the other tools — nothing is hardcoded in the scorer itself.

```bash
# Default — stale database, Darius scores C
SALES_DB_VERSION=v1 uvicorn app:app --reload --port 8000

# After "fix" — correct database, Darius scores A
SALES_DB_VERSION=v2 uvicorn app:app --reload --port 8000
```

All other prospects use deterministic random data seeded from their name/company.

## Metrics

Three LLM-judge metrics are used to evaluate each enrichment:

| Metric | What it checks |
|---|---|
| **ICP Grade Accuracy** | Does the A/B/C grade match the expected grade and is it supported by the listed signals? |
| **Enrichment Data Completeness** | Are all fields populated with non-null, non-placeholder values? |
| **Web Research Quality** | Does the `web_research_summary` contain specific, verifiable facts rather than generic filler? |

Each metric scores 1–5. A score of 4 or above is passing.
