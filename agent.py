"""
Sales enrichment agent — Claude Agent SDK setup.

run_enrichment_agent() is the async entrypoint used by main.py.
It takes the prospect inputs dict and an otel_link_id string, then:
  1. Builds a structured user prompt from the inputs.
  2. Creates a ClaudeSDKClient with:
       - The internal sales tools MCP server (5 fake tools)
       - WebSearch built-in tool for real web lookups
       - The otel_link_id injected into the subprocess env so that all OTel
         spans emitted by the claude CLI carry scorecard.otel_link_id as a
         resource attribute — enabling Scorecard to link the trace to the
         corresponding SDK record.
  3. Streams the agent response and returns the final enrichment report.
"""
import json
import os

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from tools import create_sales_tools_server

# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a sales intelligence agent for a B2B SaaS company. \
Your goal is to build a comprehensive lead enrichment profile that helps \
the sales team prioritise and personalise their outreach.

For every prospect you receive, you MUST call ALL SIX of the following tools \
in the order listed. Do not skip any tool, even if an earlier call returns \
"not found".

TOOL CALL ORDER
===============
1. WebSearch          — Search for recent news, funding, or press mentions about
                        the person or their company. Use a query like:
                        "<Name> <Company> news 2025" or "<Company> funding announcement"
2. crm_lookup         — Check whether this person / company exists in our CRM.
                        Pass the company name and the prospect's likely email address
                        (construct it from their name + company domain).
3. linkedin_profile_lookup
                      — Retrieve their LinkedIn profile: title, seniority, skills,
                        connections, and most recent post.
4. company_intel_lookup
                      — Pull firmographic data: headcount, ARR estimate, funding
                        stage, tech stack, and ICP signals.
5. email_finder       — Discover and verify their work email. Pass their full name
                        and the company domain (e.g. "acmecorp.com").
6. enrichment_score   — Calculate their ICP fit score. Use the contact_id from the
                        CRM lookup (or "new-lead" if not found), the seniority from
                        LinkedIn, the headcount and ARR from company intel, and the
                        count of ICP signals returned.

OUTPUT FORMAT
=============
After all six tool calls, return a single JSON object — no markdown, no prose outside
the JSON. The object must conform exactly to this shape:

{
  "contact": {
    "name": "<full name>",
    "title": "<current job title>",
    "company": "<company name>",
    "email": "<verified work email or null>",
    "linkedin_url": "<LinkedIn profile URL or null>",
    "seniority": "<C-Level / VP / Director / Manager / Senior IC>"
  },
  "company_profile": {
    "industry": "<industry vertical>",
    "headcount": <integer>,
    "arr_estimate_usd": <integer>,
    "funding_stage": "<stage>",
    "tech_stack": ["<tool>", ...],
    "recent_news": "<one sentence summary of the most relevant web search finding>",
    "icp_signals": ["<signal>", ...]
  },
  "crm_status": {
    "found": <true|false>,
    "contact_id": "<CRM ID or null>",
    "deal_stage": "<stage or null>",
    "deal_value_usd": <integer or null>,
    "assigned_rep": "<email or null>",
    "last_activity_days_ago": <integer or null>,
    "notes": "<notes or null>"
  },
  "icp": {
    "score": <float 0-100>,
    "grade": "<A|B|C>",
    "recommended_action": "<one sentence action>",
    "next_steps": ["<step 1>", "<step 2>"]
  },
  "web_research_summary": "<2-3 sentence summary of what you found via WebSearch>"
}\
"""

# JSON schema used by ClaudeAgentOptions(output_format=...) to enforce structure
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "contact": {
            "type": "object",
            "properties": {
                "name":        {"type": "string"},
                "title":       {"type": "string"},
                "company":     {"type": "string"},
                "email":       {"type": ["string", "null"]},
                "linkedin_url":{"type": ["string", "null"]},
                "seniority":   {"type": "string"},
            },
            "required": ["name", "title", "company", "email", "linkedin_url", "seniority"],
            "additionalProperties": False,
        },
        "company_profile": {
            "type": "object",
            "properties": {
                "industry":        {"type": "string"},
                "headcount":       {"type": "integer"},
                "arr_estimate_usd":{"type": "integer"},
                "funding_stage":   {"type": "string"},
                "tech_stack":      {"type": "array", "items": {"type": "string"}},
                "recent_news":     {"type": "string"},
                "icp_signals":     {"type": "array", "items": {"type": "string"}},
            },
            "required": ["industry", "headcount", "arr_estimate_usd", "funding_stage", "tech_stack", "recent_news", "icp_signals"],
            "additionalProperties": False,
        },
        "crm_status": {
            "type": "object",
            "properties": {
                "found":                  {"type": "boolean"},
                "contact_id":             {"type": ["string", "null"]},
                "deal_stage":             {"type": ["string", "null"]},
                "deal_value_usd":         {"type": ["integer", "null"]},
                "assigned_rep":           {"type": ["string", "null"]},
                "last_activity_days_ago": {"type": ["integer", "null"]},
                "notes":                  {"type": ["string", "null"]},
            },
            "required": ["found", "contact_id", "deal_stage", "deal_value_usd", "assigned_rep", "last_activity_days_ago", "notes"],
            "additionalProperties": False,
        },
        "icp": {
            "type": "object",
            "properties": {
                "score":              {"type": "number"},
                "grade":              {"type": "string", "enum": ["A", "B", "C"]},
                "recommended_action": {"type": "string"},
                "next_steps":         {"type": "array", "items": {"type": "string"}},
            },
            "required": ["score", "grade", "recommended_action", "next_steps"],
            "additionalProperties": False,
        },
        "web_research_summary": {"type": "string"},
    },
    "required": ["contact", "company_profile", "crm_status", "icp", "web_research_summary"],
    "additionalProperties": False,
}

# ── Agent Runner ──────────────────────────────────────────────────────────────

async def run_enrichment_agent(inputs: dict, otel_link_id: str) -> dict:
    """
    Run the enrichment agent for one prospect and return the report dict.

    Parameters
    ----------
    inputs : dict
        Must contain 'name'. May also contain 'company', 'domain', 'role_hint'.
    otel_link_id : str
        UUID generated by Scorecard's run_and_evaluate(). Injected into the
        claude CLI subprocess env as scorecard.otel_link_id so Scorecard can
        merge the trace spans into the corresponding SDK record.
    """
    name = inputs.get("name", "Unknown")
    company = inputs.get("company", "")
    domain = inputs.get("domain", "")
    role_hint = inputs.get("role_hint", "")

    prompt = (
        f"Please enrich this sales prospect:\n\n"
        f"**Name**: {name}\n"
        f"**Company**: {company or '(unknown)'}\n"
        f"**Company Domain**: {domain or '(unknown)'}\n"
        f"**Role Hint**: {role_hint or '(unknown)'}\n\n"
        f"Use all six tools in order and produce the enrichment report."
    )

    project_id = os.environ.get("SCORECARD_PROJECT_ID", "")

    # The `env` dict is merged into the claude CLI subprocess's environment.
    # Because the Claude Agent SDK spawns a new subprocess per query(), each
    # run inherits the parent env PLUS these overrides — so OTEL_RESOURCE_ATTRIBUTES
    # is set correctly per run without polluting the parent process's env.
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=["WebSearch"],          # built-in real web search
        mcp_servers={
            "sales-tools": create_sales_tools_server(),  # 5 fake internal tools
        },
        output_format=OUTPUT_SCHEMA,          # enforce structured JSON output
        max_turns=20,
        permission_mode="bypassPermissions",
        env={
            "OTEL_RESOURCE_ATTRIBUTES": (
                f"scorecard.project_id={project_id},"
                f"scorecard.otel_link_id={otel_link_id}"
            ),
        },
    )

    final_text = ""
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                final_text = message.result
                break
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        final_text = block.text

    # Parse the structured JSON response
    try:
        structured = json.loads(final_text)
    except (json.JSONDecodeError, TypeError):
        # Fallback: wrap raw text if the model didn't return valid JSON
        structured = {"enrichment_report": final_text}

    return structured
