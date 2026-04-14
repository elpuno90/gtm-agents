#!/usr/bin/env python3
"""
run_nrr.py — Automated NRR Intelligence Report

Reads companies from clients.csv, searches for recent news via the Anthropic
API (web_search tool), classifies each signal as Expansion Opportunity or
Churn Risk, and writes nrr_report.md with today's date in the header.

Prompt caching is applied to the system instructions so the token cost of
the cached prefix is paid only on the first call (~1.25x write premium) and
then served at ~0.1x on every subsequent company lookup in the same run.

Usage:
    ANTHROPIC_API_KEY=<key> python run_nrr.py
"""

import csv
import json
import os
import re
import time
from datetime import date
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 2048
CSV_PATH = Path("clients.csv")
REPORT_PATH = Path("nrr_report.md")

# ---------------------------------------------------------------------------
# System instructions (cached)
#
# This block is marked with cache_control so Anthropic caches it after the
# first API call. All subsequent per-company calls read it from cache at
# ~0.1x the normal input token cost.
#
# Note: the minimum cacheable prefix for claude-sonnet-4-5 is 1024
# tokens. In a production deployment the system prompt would typically be
# longer (persona details, product context, example classifications); the
# cache_control annotation is already in the right place for that expansion.
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = """\
You are a Strategic Customer Success Manager (CSM) analyst at a B2B SaaS company.
Your job is to monitor commercial signals for key enterprise accounts and translate
external news into actionable revenue intelligence.

TASK
For each company you are asked about, use the web_search tool to find news published
in the last 30 days. Focus on these three signal categories:

  1. M&A ACTIVITY — acquisitions, divestitures, mergers, joint ventures, or
     rumoured deals. These indicate budget reallocation, org restructuring, or
     the arrival of competing internal tools.

  2. LEADERSHIP CHANGES — new or departing CEOs, CFOs, CTOs, or board members.
     Leadership transitions often reset vendor relationships and introduce new
     priorities or budget scrutiny.

  3. SUSTAINABILITY TARGETS — new ESG commitments, carbon-neutral pledges,
     circular economy goals, or sustainability-linked financing. These frequently
     unlock new budget lines aligned to compliance and reporting tooling.

CLASSIFICATION RULES
After identifying the most commercially significant signal, classify it as exactly
one of:

  "Expansion Opportunity"
    Use when the signal suggests: available budget, strategic alignment with your
    product, org growth that creates upsell or cross-sell potential, or a new
    initiative that your platform can directly support.

  "Churn Risk"
    Use when the signal suggests: major restructuring, budget contraction,
    acquisition of capabilities that overlap with your product, loss of a key
    internal champion, or uncertainty that makes renewal conversations harder.

OUTPUT FORMAT
Respond with ONLY a JSON object — no prose, no markdown fences, no explanation
before or after the JSON:

{
  "company": "<company name>",
  "signal_found": "<1–2 sentences: what happened, when, and why it matters commercially>",
  "classification": "Expansion Opportunity" or "Churn Risk",
  "recommended_action": "<one specific, actionable next step for the CSM>"
}
"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def research_company(client: anthropic.Anthropic, company: str, industry: str) -> dict:
    """
    Call Claude with the web_search tool to research a single company.
    Returns a dict with keys: company, signal_found, classification,
    recommended_action.

    Handles the pause_turn stop reason that fires when the server-side tool
    loop hits its default iteration limit — we re-send to let Claude continue.
    """
    messages = [
        {
            "role": "user",
            "content": (
                f"Research {company} ({industry} industry). Search for news from "
                "the last 30 days covering M&A activity, leadership changes, and "
                "sustainability targets. Identify the most commercially significant "
                "signal and return your analysis as the JSON object described in "
                "your instructions."
            ),
        }
    ]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_INSTRUCTIONS,
                    # Cache the system instructions across all per-company calls.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[{"type": "web_search_20260209", "name": "web_search", "allowed_callers": ["direct"]}],
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "pause_turn":
            # The server-side web_search loop hit its iteration cap (default 10).
            # Append the assistant turn and prompt Claude to finish.
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Please finish your analysis and return the JSON result."
                    ),
                }
            )
            continue

        # Any other stop reason (e.g. max_tokens) — exit the loop.
        break

    # Pull the JSON out of the last text block in the response.
    for block in response.content:
        if block.type == "text":
            text = block.text.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass  # fall through to the error return below

    return {
        "company": company,
        "signal_found": "Automated search did not return a parseable result.",
        "classification": "Churn Risk",
        "recommended_action": "Conduct manual research before the next touchpoint.",
    }


def generate_priority_email(client: anthropic.Anthropic, account: dict) -> str:
    """
    Generate a 3-sentence outreach email for the highest-priority account.
    Reuses the cached system instructions to avoid paying the write premium again.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": SYSTEM_INSTRUCTIONS,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a 3-sentence outreach email to the CSM's contact at "
                    f"{account['company']}. The commercial context is:\n\n"
                    f"Signal: {account['signal_found']}\n"
                    f"Classification: {account['classification']}\n\n"
                    "The email should reference the specific signal by name, explain "
                    "why it is relevant to the customer's goals, and propose a brief "
                    "call. Format your output exactly as:\n"
                    "Subject: <subject line>\n\n<three sentence email body>"
                ),
            }
        ],
    )
    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    return "(Email generation failed — draft manually.)"


def build_report(results: list, today: str, top_account: dict, email: str) -> str:
    """Assemble the full nrr_report.md content."""
    lines = [
        f"# NRR Intelligence Report — {today}",
        "",
        "| Company | Signal Found | Classification | Recommended Action |",
        "|---------|-------------|----------------|--------------------|",
    ]

    for r in results:
        company = r.get("company", "")
        signal = r.get("signal_found", "").replace("|", "\\|")
        classification = r.get("classification", "")
        action = r.get("recommended_action", "").replace("|", "\\|")
        lines.append(f"| {company} | {signal} | {classification} | {action} |")

    lines += [
        "",
        "---",
        "",
        "## Priority Outreach",
        "",
        f"**Highest-priority account: {top_account['company']}**"
        f" — {top_account['signal_found']}",
        "",
        "**Draft email:**",
        "",
    ]

    for line in email.splitlines():
        lines.append(f"> {line}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY environment variable is not set.\n"
            "Run: export ANTHROPIC_API_KEY=<your key>"
        )

    client = anthropic.Anthropic(api_key=api_key)

    # Read companies from CSV.
    companies = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            companies.append(
                {"company": row["Company"].strip(), "industry": row["Industry"].strip()}
            )

    if not companies:
        raise ValueError(f"No companies found in {CSV_PATH}.")

    print(f"Researching {len(companies)} companies with model {MODEL}...")
    print("(System instructions will be cached after the first call.)\n")

    results = []
    for entry in companies:
        company, industry = entry["company"], entry["industry"]
        print(f"  [{len(results) + 1}/{len(companies)}] {company} ({industry})...", end=" ", flush=True)
        result = research_company(client, company, industry)
        results.append(result)
        print(result["classification"])
        if len(results) < len(companies):
            print("  Waiting 30s before next call...", flush=True)
            time.sleep(30)

    # Select the highest-priority account for the outreach section.
    # Prefer Expansion Opportunity; fall back to the first result.
    top = next(
        (r for r in results if r["classification"] == "Expansion Opportunity"),
        results[0],
    )

    print(f"\nGenerating priority outreach email for {top['company']}...")
    email = generate_priority_email(client, top)

    today = date.today().strftime("%B %d, %Y")
    report = build_report(results, today, top, email)

    report = re.sub(r'</?cite[^>]*>', '', report)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
