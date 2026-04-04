# jobfit

A local tool for tracking job opportunities and scoring your CV against them using GPT-4o.

Add jobs by scraping a company's job board or pasting a URL/PDF — jobfit extracts structured data from each posting, stores it locally, and lets you score your fit with two levels of AI strictness.

## Setup

**1. Install dependencies**

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

**2. Configure your OpenAI key**

Create `config.env` in the project root:

```
OPENAI_KEY=sk-...
```

Scoring is disabled without this key; scraping still works (PDFs are saved, JSON analysis is skipped).

**3. Run the app**

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Adding jobs

### Via the UI

Use the **Add Job** form on the home page. Paste a job posting URL or upload a PDF/TXT file — the app renders it, extracts structured data via GPT-4o-mini, and stores it under `data/<company>/`.

### Via the scraper (Lever boards)

```bash
python lever_scraper.py <company-slug> [--limit N] [-s 1,3]
```

For example, to scrape Mistral's Lever board:

```bash
python lever_scraper.py mistral --limit 10
```

The scraper prompts you to filter by job category unless you pass `-s <numbers>`.

### Generic scraper

For any job board, given a base URL and a regex pattern matching job links:

```bash
python scraper.py <base_url> <link_pattern_regex> [--analyse] [--limit N]
```

## Scoring

Upload your CV (PDF) using the button in the navbar. Once uploaded, each job page shows a **Score** button. Scores are cached and invalidated automatically if you replace your CV.

Two modes are available via the **Brutal mode** toggle:

| Mode | Behaviour |
|------|-----------|
| Normal | Expert recruiter perspective. Makes professional inferences from implied experience. |
| Brutal | Conservative scoring with a hard domain-mismatch penalty. Scores 8+ are rare. |

Both modes share an inference preamble that prevents penalising for missing explicit keywords when the underlying competence is clearly implied by the CV.

### Score rubric

| Score | Meaning | Shortlist? |
|-------|---------|------------|
| 10 | Near-perfect fit, exceeds all requirements | Yes |
| 9 | Excellent fit, only minor gaps | Yes |
| 8 | Strong fit, gaps easily bridgeable | Likely |
| 7 | Good fit, some notable gaps | Likely |
| 6 | Borderline positive | Maybe |
| 5 | Borderline negative | Maybe |
| 4 | Significant gaps | Unlikely |
| 3 | Poor fit, missing critical requirements | No |
| 2 | Fundamental mismatch | No |
| 1 | No meaningful match | No |

### Candidate notes

The **Notes** button in the navbar lets you add free-text context that gets injected into every scoring prompt (skills not on your CV, depth of experience behind a terse bullet, publications, etc.). The navbar button turns yellow when notes are active. After updating notes, re-score any roles that matter — notes changes do not auto-invalidate cached scores.

## Data layout

Everything lives under `data/`:

```
data/
  _cv.pdf                          # your uploaded CV
  _notes.txt                       # optional scoring context
  <company>/
    _company.json                  # company name and description
    <role_id>.json                 # structured job data
    <role_id>.pdf                  # rendered job page
    _scores/
      <role_id>_normal.json        # cached normal-mode score
      <role_id>_brutal.json        # cached brutal-mode score
```

No database — the filesystem is the database.
