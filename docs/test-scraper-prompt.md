# test_scraper_prompt.py

Standalone testbed for the generic scraper's OpenAI call. Useful for debugging
timeouts or bad extractions without going through the full Flask UI.

## What it does

1. Fetches a careers page via Playwright (fully rendered DOM), or loads a local HTML file
2. Cleans the HTML the same way `GenericScraper` does (strips scripts, styles, SVGs; keeps only `href` and `class` attributes; caps at 80,000 chars)
3. Sends the exact same `gpt-4o-mini` prompt used by `GenericScraper`
4. Prints timing, token counts, and the extracted jobs

## Usage

```bash
# Fetch a live URL
python test_scraper_prompt.py https://company.com/careers

# Longer timeouts (seconds)
python test_scraper_prompt.py https://company.com/careers --timeout 120 --openai-timeout 180

# Save cleaned HTML to avoid re-fetching on repeated runs
python test_scraper_prompt.py https://company.com/careers --save-html page.html

# Re-run the OpenAI call against a previously saved HTML file
python test_scraper_prompt.py --html page.html

# Load any local HTML file
python test_scraper_prompt.py --html /tmp/careers.html
```

## Options

| Flag | Default | Description |
|---|---|---|
| `url` | — | Careers page URL to fetch via Playwright |
| `--html FILE` | — | Load HTML from a local file instead of fetching (mutually exclusive with `url`) |
| `--timeout SEC` | 90 | Playwright fetch timeout |
| `--openai-timeout SEC` | 120 | OpenAI request timeout |
| `--save-html FILE` | — | Save the cleaned HTML to a file for later reuse |

## Output

```
[fetch] Launching Playwright → https://…
[fetch] Done in 4.2s, raw HTML size: 312,000 chars
[clean] Cleaned HTML size: 78,431 chars (cap 80,000)
[prompt] Total prompt length: 79,204 chars
[openai] Sending to gpt-4o-mini (timeout=120s)…
[openai] Done in 8.3s — prompt_tokens=18432, completion_tokens=712
────────────────────────────────────────────────────────────
company   : 'Acme Corp'
categories: ['Engineering', 'Sales', 'Operations']
next_page : ''
jobs      : 14 found
────────────────────────────────────────────────────────────
  [  1] 'Senior Backend Engineer'                      cat='Engineering'  co='Acme Corp'
        url: https://jobs.acme.com/senior-backend-engineer
  ...
```

## Debugging timeouts

- If Playwright times out: increase `--timeout`
- If OpenAI times out: the prompt is likely too long (check the `prompt length` line). The cleaned HTML is capped at 80,000 chars — if the page is hitting that cap, the content may be too dense for the model to process quickly. Try `--save-html` and manually trim the HTML before re-running with `--html`.
- Token counts in the output tell you exactly how much of the context window is being used.
