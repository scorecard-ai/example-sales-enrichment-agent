"""
FastAPI web server for the Sales Enrichment Agent.

Run:  uvicorn app:app --reload --port 8000
Then: open http://localhost:8000
"""
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ── Env setup (must happen before agent import) ───────────────────────────────
load_dotenv(".env.keys")
load_dotenv()

SCORECARD_API_KEY = os.environ.get("SCORECARD_API_KEY", "")
os.environ.setdefault("BETA_TRACING_ENDPOINT", "https://tracing.scorecard.io/otel")
if SCORECARD_API_KEY:
    os.environ.setdefault(
        "OTEL_EXPORTER_OTLP_HEADERS", f"authorization=Bearer {SCORECARD_API_KEY}"
    )
os.environ.setdefault("ENABLE_BETA_TRACING_DETAILED", "1")

from agent import run_enrichment_agent  # noqa: E402

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Sales Enrichment Agent")


class SearchInput(BaseModel):
    query: str  # free-form, e.g. "Sarah Chen VP Eng at Databricks"


@app.get("/", response_class=HTMLResponse)
async def root():
    return Path("static/index.html").read_text()


@app.post("/enrich")
async def enrich(body: SearchInput):
    otel_link_id = str(uuid.uuid4())
    print(f"[server] query={body.query!r} [{otel_link_id[:8]}]")
    try:
        result = await run_enrichment_agent({"query": body.query}, otel_link_id)
        print(f"[server] success — top-level keys: {list(result.keys())}")
        return result
    except Exception as e:
        print(f"[server] ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
