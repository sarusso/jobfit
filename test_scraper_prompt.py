#!/usr/bin/env python3
"""
test_scraper_prompt.py — Testbed for the generic scraper OpenAI call.

Fetches a URL with Playwright (or reads a local HTML file / accepts pasted HTML),
then runs the same gpt-4o-mini prompt used by GenericScraper and prints the result.

Usage:
    python test_scraper_prompt.py <url>
    python test_scraper_prompt.py <url> --timeout 120
    python test_scraper_prompt.py --html path/to/file.html
    python test_scraper_prompt.py <url> --save-html page.html   # save fetched HTML for reuse
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from openai import OpenAI
from playwright.sync_api import sync_playwright

_CONFIG_FILE = Path(__file__).parent / "config.env"
_MAX_HTML_CHARS = 80_000


def _load_config() -> dict:
    config = {}
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip()
    return config


def _fetch_html(url: str, timeout_ms: int) -> str:
    print(f"[fetch] Launching Playwright → {url}", flush=True)
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        html = page.content()
        browser.close()
    print(f"[fetch] Done in {time.time() - t0:.1f}s, raw HTML size: {len(html):,} chars", flush=True)
    return html


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "svg", "noscript", "head", "iframe"]):
        tag.decompose()
    for tag in soup.find_all(True):
        keep = {}
        if tag.get("href"):
            keep["href"] = tag["href"]
        if tag.get("class"):
            keep["class"] = tag["class"]
        tag.attrs = keep
    cleaned = str(soup)[:_MAX_HTML_CHARS]
    print(f"[clean] Cleaned HTML size: {len(cleaned):,} chars (cap {_MAX_HTML_CHARS:,})", flush=True)
    return cleaned


def _make_prompt(page_url: str, page_html: str) -> str:
    return (
        "You are analyzing the HTML of a page that may be a single company careers page "
        "OR a listing page with job postings from multiple different companies "
        "(e.g. a job board, a 'who's hiring' thread, an aggregator).\n\n"
        f"Page URL: {page_url}\n\n"
        "HTML (scripts, styles and non-essential attributes removed):\n"
        f"{page_html}\n\n"
        "Extract EVERY individual job posting linked anywhere on this page, across ALL companies.\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "company": "Single company name if the page belongs to one company, otherwise empty string",\n'
        '  "categories": ["list of unique department or job category names found across all jobs"],\n'
        '  "jobs": [\n'
        '    {"title": "Job Title", "url": "<href value>", "category": "Department or General", "company": "Company name for this specific job"}\n'
        '  ],\n'
        '  "next_page": "URL of the next page of job listings if a pagination link exists, otherwise empty string"\n'
        "}\n\n"
        "Rules:\n"
        "- Include ALL job postings found, not just those from the first company\n"
        "- Only include <a href> links that point to individual job postings\n"
        "- Use the href value exactly as it appears in the HTML\n"
        "- Set company per job to the company that posted it\n"
        "- If no department is labelled for a job, use 'General'\n"
        "- Leave the top-level company field empty if multiple companies are present\n"
        "- Set next_page only if there is a clearly labelled 'next page' or pagination link — otherwise leave empty\n"
        "- Return empty lists if no jobs are found"
    )


def main():
    parser = argparse.ArgumentParser(description="Test generic scraper OpenAI prompt")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", help="Careers page URL to fetch via Playwright")
    group.add_argument("--html", metavar="FILE", help="Load HTML from a local file instead of fetching")
    parser.add_argument("--timeout", type=int, default=90, metavar="SEC",
                        help="Playwright fetch timeout in seconds (default: 90)")
    parser.add_argument("--save-html", metavar="FILE",
                        help="Save the fetched/cleaned HTML to a file for later reuse")
    parser.add_argument("--openai-timeout", type=int, default=120, metavar="SEC",
                        help="OpenAI request timeout in seconds (default: 120)")
    args = parser.parse_args()

    config = _load_config()
    api_key = config.get("OPENAI_KEY")
    if not api_key:
        print("ERROR: OPENAI_KEY not found in config.env", file=sys.stderr)
        sys.exit(1)

    # ── Get HTML ──
    if args.html:
        html_raw = Path(args.html).read_text()
        page_url = f"file://{Path(args.html).resolve()}"
        print(f"[source] Loaded HTML from {args.html} ({len(html_raw):,} chars)", flush=True)
        cleaned = _clean_html(html_raw)
    else:
        html_raw = _fetch_html(args.url, timeout_ms=args.timeout * 1000)
        page_url = args.url
        cleaned = _clean_html(html_raw)

    if args.save_html:
        Path(args.save_html).write_text(cleaned)
        print(f"[save] Cleaned HTML saved to {args.save_html}", flush=True)

    # ── Build prompt ──
    prompt = _make_prompt(page_url, cleaned)
    print(f"\n[prompt] Total prompt length: {len(prompt):,} chars", flush=True)

    # ── OpenAI call ──
    client = OpenAI(api_key=api_key)
    print(f"[openai] Sending to gpt-4o-mini (timeout={args.openai_timeout}s)…", flush=True)
    t0 = time.time()
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            timeout=args.openai_timeout,
        )
    except Exception as e:
        print(f"\n[ERROR] OpenAI call failed after {time.time() - t0:.1f}s: {e}", file=sys.stderr)
        sys.exit(1)

    elapsed = time.time() - t0
    content = response.choices[0].message.content
    usage = response.usage
    print(f"[openai] Done in {elapsed:.1f}s — "
          f"prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}", flush=True)

    # ── Parse + print result ──
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"\n[ERROR] JSON parse failed: {e}")
        print("Raw response:\n", content)
        sys.exit(1)

    print(f"\n{'─'*60}")
    print(f"company   : {data.get('company', '')!r}")
    print(f"categories: {data.get('categories', [])}")
    print(f"next_page : {data.get('next_page', '')!r}")
    jobs = data.get("jobs", [])
    print(f"jobs      : {len(jobs)} found")
    print(f"{'─'*60}")
    for i, job in enumerate(jobs, 1):
        print(f"  [{i:3}] {job.get('title', '?')!r:<50}  cat={job.get('category', '')!r}  co={job.get('company', '')!r}")
        print(f"        url: {job.get('url', '')}")

    print(f"\n[done] Full JSON written to stdout below:")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
