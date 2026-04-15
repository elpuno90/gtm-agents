# NRR Guardian — CS Intelligence Agent

A lightweight AI agent that monitors enterprise accounts for expansion and churn signals, scores them by urgency, and drafts priority outreach — built with the Anthropic API and Claude Code. Can be adapted to MM/SMB.

## What it does

Point it at a list of accounts. Within ~2 minutes it researches live news across all of them, classifies each signal as an expansion opportunity or churn risk, assigns an urgency score from 1–10, and drafts a priority outreach email for the highest-scoring account.

Signals it catches: M&A activity, executive departures, new sustainability targets, funding rounds, divestitures, competitor acquisitions.

## Why I built it

I wanted to explore how AI agents can augment strategic CS workflows — specifically the Monday morning question of "where do I call first?" The agent replaces 2–3 hours of manual research with a single command and a dated report.

## Files

| File | Purpose |
|------|---------|
| `run_nrr.py` | Main agent script — reads `clients.csv`, researches each company, writes `nrr_report.md` |
| `clients.csv` | Account list (company name + industry) |
| `nrr_report.md` | Latest generated report with scores, signals, and outreach draft |

## Usage

```bash
# Install dependency
pip install anthropic

# Set your API key
export ANTHROPIC_API_KEY=your-key-here

# Run
python3 run_nrr.py
```

Open `index.html` in a browser (via `python3 -m http.server 8000`) for an interactive dashboard view.

## Stack

- Anthropic API (`claude-sonnet-4-5`) with web search tool
- Python 3, no framework dependencies
- Prompt caching on system instructions for cost efficiency

## Next steps

**Scheduled automation via GitHub Actions**  
The natural next step is removing the manual `python3 run_nrr.py` trigger entirely. A GitHub Actions workflow running on a weekly cron schedule would execute the agent automatically every Monday morning on GitHub's servers, then commit the updated `nrr_report.md` back to the repo — creating a living report with week-over-week git history, no laptop required.

**Expand the account list**  
`clients.csv` can be pointed at any set of companies. A pre-interview workflow: populate it with a target company's known enterprise customers, run the agent, and walk in with a live intelligence brief tailored to their world.

**Connect the dashboard to live data**  
`index.html` currently loads from the last generated report. Wiring the "Analyze" button directly to the Anthropic API would allow on-demand lookups of any company in real time — turning the dashboard into an interactive tool rather than a static report viewer.
