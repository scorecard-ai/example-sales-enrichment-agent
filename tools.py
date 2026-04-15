"""
Mock internal sales tools for the enrichment agent.

These simulate real internal systems (CRM, LinkedIn data connector, company
intelligence DB, email discovery service, ICP scorer) but return realistic
fake data seeded deterministically from the input so results are consistent
across runs for the same person.

For the demo prospect "Darius Emrani", two hardcoded database versions exist:
  v1 (SALES_DB_VERSION=v1, the default): stale/wrong record → C grade
  v2 (SALES_DB_VERSION=v2): correct, up-to-date record → A grade

All other prospects fall through to the deterministic random logic.
"""
import json
import os
import random

from claude_agent_sdk import tool, create_sdk_mcp_server


# ── Database version ──────────────────────────────────────────────────────────
# Set SALES_DB_VERSION=v2 in .env to switch to the corrected database.
DB_VERSION = os.environ.get("SALES_DB_VERSION", "v1")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rng(seed_str: str) -> random.Random:
    """Deterministic RNG seeded from a string — same input always gives same data."""
    return random.Random(sum(ord(c) for c in seed_str.lower()))

def _is_darius(name: str) -> bool:
    n = name.lower()
    return "darius" in n and "emrani" in n

def _is_scorecard(company: str) -> bool:
    return "scorecard" in company.lower()


# ── Darius Emrani / Scorecard fixtures ───────────────────────────────────────
#
# v1 — stale record: Darius is listed as a Senior IC at a tiny pre-seed startup.
#      The scoring formula will naturally produce a C from this data.
#
# v2 — correct record: Darius is Founder & CEO of a Series A company.
#      The scoring formula will naturally produce an A from this data.

_DARIUS_LINKEDIN = {
    "v1": {
        "found": True,
        "name": "Darius Emrani",
        "current_title": "Software Engineer",
        "company": "Scorecard",
        "seniority": "Senior IC",
        "location": "San Francisco Bay Area",
        "connections": 341,
        "years_at_company": 1,
        "total_experience_years": 3,
        "education": "UC Berkeley — BA Economics",
        "top_skills": ["Python", "SQL", "API Design", "Product Management", "Startups"],
        "recent_activity": "Liked a post about early-stage startup hiring",
        "linkedin_url": "https://www.linkedin.com/in/darius-emrani-4812",
        "_db_note": "[v1] Last synced 2024-06-01 — record may be outdated",
    },
    "v2": {
        "found": True,
        "name": "Darius Emrani",
        "current_title": "Founder & CEO",
        "company": "Scorecard",
        "seniority": "C-Level / Founder",
        "location": "San Francisco Bay Area",
        "connections": 1840,
        "years_at_company": 2,
        "total_experience_years": 7,
        "education": "UC Berkeley — BA Economics",
        "top_skills": [
            "Enterprise Sales", "B2B SaaS", "AI/ML Platforms",
            "Go-to-Market", "Strategic Partnerships",
        ],
        "recent_activity": (
            "Posted: 'Announcing Scorecard's Series A — we're building "
            "the simulation platform for agent self-improvement'"
        ),
        "linkedin_url": "https://www.linkedin.com/in/darius-emrani-4812",
        "_db_note": "[v2] Last synced 2026-04-01 — current",
    },
}

_SCORECARD_COMPANY = {
    "v1": {
        "found": True,
        "company_name": "Scorecard",
        "industry": "Developer Tools / Infrastructure",
        "headcount": 8,
        "headcount_range": "8–12",
        "arr_estimate_usd": 0,
        "funding_stage": "Pre-Seed",
        "latest_round": "Bootstrapped — 2024",
        "total_funding_usd": 0,
        "founded_year": 2024,
        "hq_location": "San Francisco, CA",
        "tech_stack": ["Python", "PostgreSQL", "AWS"],
        "icp_signals": [],
        "website": "https://www.scorecard.io",
        "_db_note": "[v1] Stale record — data last refreshed 2024-06-01",
    },
    "v2": {
        "found": True,
        "company_name": "Scorecard",
        "industry": "AI / Developer Tools",
        "headcount": 85,
        "headcount_range": "85–110",
        "arr_estimate_usd": 12_000_000,
        "funding_stage": "Series A",
        "latest_round": "$18M Series A — 2025",
        "total_funding_usd": 22_000_000,
        "founded_year": 2023,
        "hq_location": "San Francisco, CA",
        "tech_stack": [
            "Python", "TypeScript", "React", "AWS",
            "PostgreSQL", "Kafka", "Kubernetes",
        ],
        "icp_signals": [
            "Engineering headcount growing >35% YoY",
            "Raised Series A in last 12 months — scaling GTM team",
            "Active job postings for DevOps / Platform roles",
            "Open source project with >2k GitHub stars",
        ],
        "website": "https://www.scorecard.io",
        "_db_note": "[v2] Updated record — data last refreshed 2026-04-01",
    },
}

_SCORECARD_CRM = {
    "v1": {
        "found": False,
        "message": "No record found for 'Scorecard' in Salesforce.",
        "recommendation": "Create a new lead record and enroll in an outbound sequence.",
        "_db_note": "[v1] Account not yet in CRM",
    },
    "v2": {
        "found": True,
        "contact_id": "SF-089234",
        "company": "Scorecard",
        "email": "darius@scorecard.io",
        "deal_stage": "Demo Scheduled",
        "deal_value_usd": 95_000,
        "assigned_rep": "carol.hayes@acme-sales.io",
        "last_activity_days_ago": 4,
        "notes": (
            "Champion confirmed: Darius (CEO). Exec sponsor loop closed. "
            "Strong intent — moving to proposal next week."
        ),
        "tags": ["enterprise", "hot_lead", "champion_identified"],
        "_db_note": "[v2] Synced from enrichment pipeline — refreshed 2026-04-01",
    },
}


# ── Tool 1: CRM Lookup ────────────────────────────────────────────────────────

@tool(
    "crm_lookup",
    (
        "Search the internal Salesforce CRM for an existing lead or contact record. "
        "Pass the company name and the prospect's email (or email domain) to look up "
        "their deal stage, assigned rep, deal value, and recent activity notes."
    ),
    {"company_name": str, "contact_email": str},
)
async def crm_lookup(args: dict) -> dict:
    company = args.get("company_name", "")
    email = args.get("contact_email", "")

    # Darius / Scorecard fixture
    if _is_scorecard(company) or (_is_darius(email.replace("@", " ").replace(".", " "))):
        result = _SCORECARD_CRM[DB_VERSION]
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}

    rng = _rng(company + email)

    if rng.random() < 0.28:
        result = {
            "found": False,
            "message": f"No record found for '{email or company}' in Salesforce.",
            "recommendation": "Create a new lead record and enroll in an outbound sequence.",
        }
    else:
        stages = [
            "Lead", "MQL", "Qualified", "Demo Scheduled",
            "Proposal Sent", "Negotiation", "Closed Won",
        ]
        result = {
            "found": True,
            "contact_id": f"SF-{abs(hash(company + email)) % 999999:06d}",
            "company": company,
            "email": email,
            "deal_stage": rng.choice(stages),
            "deal_value_usd": rng.choice([12_000, 28_000, 60_000, 95_000, 180_000, 320_000]),
            "assigned_rep": rng.choice([
                "alice.morgan@acme-sales.io",
                "bob.shaw@acme-sales.io",
                "carol.hayes@acme-sales.io",
            ]),
            "last_activity_days_ago": rng.randint(2, 75),
            "notes": rng.choice([
                "Champion identified: VP Eng. Exec sponsor still TBD.",
                "Expressed interest in enterprise tier; requested security review docs.",
                "Currently evaluating us against Competitor X — send comparison sheet.",
                "Budget confirmed for Q2. Procurement review in progress.",
                "Discovery call went well; follow-up demo scheduled next week.",
                "Expansion opportunity — currently on Starter, wants to move to Pro.",
            ]),
            "tags": rng.sample(
                ["enterprise", "hot_lead", "champion_identified", "multi-year", "expansion", "at_risk"],
                k=rng.randint(1, 3),
            ),
        }

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# ── Tool 2: LinkedIn Profile Lookup ──────────────────────────────────────────

@tool(
    "linkedin_profile_lookup",
    (
        "Retrieve a person's LinkedIn profile via the internal LinkedIn data connector. "
        "Returns their current title, seniority level, years at company, key skills, "
        "number of connections, and a summary of their most recent post or activity."
    ),
    {"full_name": str, "company": str},
)
async def linkedin_profile_lookup(args: dict) -> dict:
    name = args.get("full_name", "")
    company = args.get("company", "")

    # Darius Emrani fixture
    if _is_darius(name):
        result = _DARIUS_LINKEDIN[DB_VERSION]
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}

    rng = _rng(name + company)

    if rng.random() < 0.08:
        return {"content": [{"type": "text", "text": json.dumps({
            "found": False,
            "message": f"LinkedIn profile not found for '{name}'.",
            "tip": "Try including the company name, or search by email domain.",
        }, indent=2)}]}

    titles = [
        "VP of Engineering", "Director of Product", "Head of Platform Engineering",
        "Chief Technology Officer", "VP of Marketing", "Chief Revenue Officer",
        "Engineering Manager", "Head of Growth", "VP of Operations",
        "Co-Founder & CTO", "Director of Sales Engineering", "Head of Data",
    ]
    result = {
        "found": True,
        "name": name,
        "current_title": rng.choice(titles),
        "company": company,
        "seniority": rng.choice(["C-Level / Founder", "VP", "Director", "Manager", "Senior IC"]),
        "location": rng.choice([
            "San Francisco Bay Area", "New York City", "Austin, TX",
            "Seattle, WA", "Boston, MA", "Remote",
        ]),
        "connections": rng.randint(320, 2800),
        "years_at_company": rng.randint(1, 8),
        "total_experience_years": rng.randint(7, 22),
        "education": rng.choice([
            "Stanford University — BS Computer Science",
            "MIT — MS Electrical Engineering & CS",
            "UC Berkeley — BA Economics",
            "Carnegie Mellon — MS Software Engineering",
            "Harvard Business School — MBA",
            "Georgia Tech — BS Computer Engineering",
        ]),
        "top_skills": rng.sample([
            "Enterprise Sales", "B2B SaaS", "Cloud Infrastructure", "Product Strategy",
            "Revenue Growth", "Go-to-Market", "Team Leadership", "DevOps",
            "Customer Success", "Data Engineering", "Strategic Partnerships",
        ], k=5),
        "recent_activity": rng.choice([
            "Published post: 'Why we migrated our entire data platform to the lakehouse architecture — and what we learned'",
            "Shared: '10 SaaS metrics every founder should obsess over in 2026'",
            "Commented on a thread about AI-assisted code review at scale",
            "Posted a job opening for Senior Solutions Engineer — SF or Remote",
            "Liked and reshared: 'How we scaled from $10M to $100M ARR in 18 months'",
            "Posted: 'We just closed our Series B — here's what's next for our team'",
        ]),
        "linkedin_url": (
            f"https://www.linkedin.com/in/{name.lower().replace(' ', '-')}"
            f"-{abs(hash(name)) % 9999:04d}"
        ),
    }

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# ── Tool 3: Company Intel Lookup ──────────────────────────────────────────────

@tool(
    "company_intel_lookup",
    (
        "Query the internal company intelligence database for firmographic data. "
        "Returns headcount, ARR estimate, funding stage, total funding, tech stack, "
        "headquarters location, and ICP signals detected for this account."
    ),
    {"company_name": str},
)
async def company_intel_lookup(args: dict) -> dict:
    company = args.get("company_name", "")

    # Scorecard fixture
    if _is_scorecard(company):
        result = _SCORECARD_COMPANY[DB_VERSION]
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}

    rng = _rng(company)

    if rng.random() < 0.07:
        return {"content": [{"type": "text", "text": json.dumps({
            "found": False,
            "message": f"'{company}' not found in the company intelligence database.",
            "suggestion": "Try the full legal name or check for recent acquisitions / rebrandings.",
        }, indent=2)}]}

    headcount = rng.choice([18, 45, 130, 380, 900, 2400, 9000])
    arr = rng.choice([800_000, 4_000_000, 14_000_000, 45_000_000, 160_000_000])
    round_size = rng.randint(8, 90)
    round_series = rng.choice(["Seed", "Series A", "Series B", "Series C"])

    result = {
        "found": True,
        "company_name": company,
        "industry": rng.choice([
            "Developer Tools / Infrastructure", "Data & Analytics",
            "FinTech / Payments", "HealthTech / Digital Health",
            "Enterprise SaaS", "Security", "E-commerce Infrastructure",
        ]),
        "headcount": headcount,
        "headcount_range": f"{headcount}–{headcount + rng.randint(25, 200)}",
        "arr_estimate_usd": arr,
        "funding_stage": rng.choice([
            "Bootstrapped", "Seed", "Series A", "Series B",
            "Series C", "Late Stage / Pre-IPO", "Public (NYSE/NASDAQ)",
        ]),
        "latest_round": f"${round_size}M {round_series} — {rng.randint(2022, 2025)}",
        "total_funding_usd": arr * rng.randint(3, 12),
        "founded_year": rng.randint(2013, 2022),
        "hq_location": rng.choice([
            "San Francisco, CA", "New York, NY", "Austin, TX",
            "Seattle, WA", "Boston, MA", "Remote-First",
        ]),
        "tech_stack": rng.sample([
            "AWS", "GCP", "Azure", "Kubernetes", "Terraform",
            "Python", "Go", "TypeScript", "React",
            "PostgreSQL", "Snowflake", "Kafka", "Datadog", "Grafana",
        ], k=rng.randint(5, 8)),
        "icp_signals": rng.sample([
            "Engineering headcount growing >35% YoY",
            "Raised Series B in last 18 months — scaling GTM team",
            "Active job postings for DevOps / Platform roles",
            "Open source project with >2k GitHub stars",
            "Tech stack includes tools we integrate natively with",
            "Recent product launch in our target vertical",
            "Competitor churned from this account 6 months ago",
            "Featured speaker at recent industry conference",
        ], k=rng.randint(2, 4)),
        "website": f"https://www.{company.lower().replace(' ', '').replace('.', '').replace(',', '')}.com",
    }

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# ── Tool 4: Email Finder ──────────────────────────────────────────────────────

@tool(
    "email_finder",
    (
        "Use the internal email discovery and SMTP verification service to find a "
        "prospect's work email address. Pass their full name and the company domain "
        "(e.g. 'acmecorp.com'). Returns the discovered email, confidence score, and "
        "verification status."
    ),
    {"full_name": str, "company_domain": str},
)
async def email_finder(args: dict) -> dict:
    name = args.get("full_name", "")
    domain = args.get("company_domain", "").lstrip("@").strip()

    # Darius always resolves cleanly regardless of DB version
    if _is_darius(name):
        result = {
            "found": True,
            "email": "darius@scorecard.io",
            "confidence_pct": 99,
            "confidence_label": "high",
            "verification_status": "smtp_verified",
            "data_sources": ["company_website_scrape", "linkedin_data_partner"],
            "last_verified": "2026-04-01",
        }
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}

    rng = _rng(name + domain)

    parts = name.lower().split()
    first = parts[0] if parts else "unknown"
    last = parts[-1] if len(parts) > 1 else "contact"

    if rng.random() < 0.14:
        return {"content": [{"type": "text", "text": json.dumps({
            "found": False,
            "confidence_pct": 0,
            "message": f"Could not verify an email for '{name}' at '{domain}'.",
            "patterns_tried": [
                f"{first}.{last}@{domain}",
                f"{first[0]}{last}@{domain}",
                f"{first}@{domain}",
            ],
        }, indent=2)}]}

    email = rng.choice([
        f"{first}.{last}@{domain}",
        f"{first[0]}{last}@{domain}",
        f"{first}@{domain}",
    ])
    confidence = rng.randint(76, 99)

    result = {
        "found": True,
        "email": email,
        "confidence_pct": confidence,
        "confidence_label": "high" if confidence >= 85 else "medium",
        "verification_status": rng.choice([
            "smtp_verified", "mx_record_accepted", "pattern_match_high_confidence",
        ]),
        "data_sources": rng.sample([
            "company_website_scrape", "linkedin_data_partner",
            "email_database_match", "domain_pattern_analysis",
        ], k=2),
        "last_verified": f"2026-{rng.randint(1, 3):02d}-{rng.randint(1, 28):02d}",
    }

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# ── Tool 5: Enrichment Score ──────────────────────────────────────────────────
#
# No fixture needed here — the score is computed from the data returned by the
# previous four tools. With v1 data (Senior IC, 8 headcount, $0 ARR, 0 signals)
# the formula naturally produces a C. With v2 data (Founder, 85 headcount,
# $12M ARR, 4 signals) it naturally produces an A.

@tool(
    "enrichment_score",
    (
        "Calculate an ICP (Ideal Customer Profile) fit score for a prospect based on "
        "their seniority, company headcount, ARR estimate, and number of positive ICP "
        "signals found. Returns a 0–100 score, letter grade (A/B/C), and a recommended "
        "next action for the sales team."
    ),
    {
        "contact_id": str,
        "seniority": str,
        "company_headcount": int,
        "arr_estimate_usd": int,
        "icp_signals_count": int,
    },
)
async def enrichment_score(args: dict) -> dict:
    contact_id = args.get("contact_id", "unknown")
    seniority = args.get("seniority", "").lower()
    headcount = args.get("company_headcount", 0)
    arr = args.get("arr_estimate_usd", 0)
    signals = args.get("icp_signals_count", 0)
    rng = _rng(contact_id + seniority)

    # Weighted scoring components (each 0–100)
    title_score = 92 if any(kw in seniority for kw in ["c-level", "founder", "vp", "director", "head"]) else 52
    size_score = 88 if 40 <= headcount <= 6000 else (65 if headcount > 6000 else 32)
    arr_score = 90 if 4_000_000 <= arr <= 250_000_000 else (62 if arr > 0 else 38)
    signal_score = min(100, 45 + signals * 14)

    raw = (
        title_score * 0.35
        + size_score * 0.25
        + arr_score * 0.25
        + signal_score * 0.15
    )
    final = round(min(100.0, max(0.0, raw + rng.uniform(-2.5, 2.5))), 1)
    grade = "A" if final >= 80 else ("B" if final >= 60 else "C")

    result = {
        "contact_id": contact_id,
        "icp_score": final,
        "grade": grade,
        "score_breakdown": {
            "title_seniority_fit":  title_score,
            "company_size_fit":     size_score,
            "revenue_band_fit":     arr_score,
            "intent_signal_fit":    signal_score,
        },
        "recommended_action": {
            "A": "High priority — route to senior AE for immediate personalised outreach.",
            "B": "Good fit — enrol in targeted nurture sequence; schedule discovery call.",
            "C": "Below threshold — add to low-touch drip; revisit in 90 days.",
        }[grade],
        "suggested_next_steps": rng.sample([
            "Send personalised cold email referencing the company's recent funding round",
            "Request warm intro via shared LinkedIn connection",
            "Invite to upcoming industry webinar or virtual roundtable",
            "Add to target account ABM campaign with custom landing page",
            "Schedule 15-min discovery call via Calendly link",
            "Send relevant case study from same industry vertical",
        ], k=2),
    }

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# ── MCP Server Factory ────────────────────────────────────────────────────────

def create_sales_tools_server():
    """
    Create an in-process MCP server that exposes all five internal sales tools.
    Pass the returned server object to ClaudeAgentOptions(mcp_servers=...).

    The active database version is read from SALES_DB_VERSION at import time:
      v1 (default) — stale data, Darius Emrani scores C
      v2            — correct data, Darius Emrani scores A
    """
    return create_sdk_mcp_server(
        "sales-tools",
        tools=[
            crm_lookup,
            linkedin_profile_lookup,
            company_intel_lookup,
            email_finder,
            enrichment_score,
        ],
    )
