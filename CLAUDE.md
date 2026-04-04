# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
source venv/bin/activate
python app.py          # Flask dev server on http://127.0.0.1:5000
```

## Scrapers

```bash
# Generic scraper (Lever-style boards via URL + regex pattern)
python scraper.py <base_url> <link_pattern_regex> [--analyse] [--limit N] [--data-dir data]

# Lever-specific scraper
python lever_scraper.py <company-slug> [-s 1,3] [--limit N] [--data-dir data]
```

Both scrapers prompt interactively to filter by job category unless `-s` is passed.

## Configuration

`config.env` (gitignored) in the project root, format `KEY=VALUE`:
- `OPENAI_KEY` — required for AI analysis and scoring. Without it, scrapers save PDFs only and the Flask app disables scoring.

## Architecture

This is a local-only job tracking tool with two separate layers:

**Scraping layer** (`scraper.py`, `base_scraper.py`, `lever_scraper.py`)
- `scraper.py` is a standalone CLI: fetches a job board URL, renders each job page to PDF via Playwright, optionally calls OpenAI (`gpt-4o-mini`) to extract structured JSON, merges PDFs.
- `BaseScraper` is an abstract base class for board-specific scrapers. Subclasses implement `get_base_url`, `get_company_name`, `fetch_categories`, `fetch_links`. The base class handles the Playwright loop, OpenAI analysis, and file I/O.
- `LeverScraper` extends `BaseScraper` for `jobs.lever.co/<company>` boards.

**Flask UI layer** (`app.py`)
- Reads the `data/` directory at request time — no database. Each company is a subdirectory; each job is a `<role_id>.json` + optional `<role_id>.pdf`.
- Special files per company dir: `_company.json` (company metadata), `_scores/<role_id>_<mode>.json` (cached AI scores).
- Special files in `data/`: `_cv.pdf` (candidate CV), `_notes.txt` (free-text context injected into scoring prompts).
- Supports two scoring modes (`normal` / `brutal`) stored in the Flask session. Scores are cached and invalidated when the CV changes (via SHA-256 hash). Notes changes do **not** auto-invalidate scores — re-score manually if notes are updated.
- Batch scoring uses SSE (Server-Sent Events) streaming via `/score/<company>/stream`.
- JD upload (`/upload-jd`) accepts PDF, TXT, or a URL (rendered via Playwright). OpenAI (`gpt-4o-mini`) extracts structured JSON; scoring uses `gpt-4o` with the CV attached as a base64 PDF.

## Data layout

```
data/
  _cv.pdf               # candidate CV (uploaded via UI)
  _notes.txt            # optional candidate context for scoring
  <company>/
    _company.json       # {"company": "...", "description": "..."}
    <role_id>.json      # structured job data
    <role_id>.pdf       # rendered job page
    _scores/
      <role_id>_normal.json
      <role_id>_brutal.json
```

`role_id` is either a URL SHA-256 hash (scraper) or a title-derived slug (UI upload).

## Scoring design

See `docs/scoring-design.md` for rationale. Key points:
- Both scoring modes share a CV-inference preamble that instructs the LLM to make professional inferences from implied experience, not just explicit keywords.
- Brutal mode keeps a conservative rubric and domain-mismatch penalty but does not treat "keyword absent" as "skill absent".
- `data/_notes.txt` is injected as authoritative context into every scoring prompt — use it for skills/experience not explicit in the CV.
