#!/usr/bin/env python3
"""
generic_scraper.py — LLM-assisted scraper for arbitrary job board pages.

Uses Playwright to get the fully-rendered DOM, strips non-content tags,
then asks gpt-4o-mini to extract job listings and categories.

Usage (CLI):
    python generic_scraper.py <careers_url> <company_name> [--limit N]
"""

import json
import logging
import re
from urllib.parse import urljoin

log = logging.getLogger(__name__)

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from base_scraper import BaseScraper

_MAX_HTML_CHARS = 80_000


def _rendered_html(url: str, timeout_ms: int = 30_000) -> str:
    """Fetch fully-rendered DOM via Playwright and return cleaned HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content tags entirely
    for tag in soup(["script", "style", "svg", "noscript", "head", "iframe"]):
        tag.decompose()

    # Strip all attributes except href and class (massively reduces token count)
    for tag in soup.find_all(True):
        keep = {}
        if tag.get("href"):
            keep["href"] = tag["href"]
        if tag.get("class"):
            keep["class"] = tag["class"]
        tag.attrs = keep

    return str(soup)[:_MAX_HTML_CHARS]


class GenericScraper(BaseScraper):

    def build_arg_parser(self):
        parser = super().build_arg_parser()
        parser.add_argument("url", help="Careers page URL")
        parser.add_argument("company", help="Company name (used as folder name)")
        return parser

    def get_base_url(self, args):
        return args.url

    def get_company_name(self, args):
        import unicodedata
        s = unicodedata.normalize("NFKD", args.company.lower())
        s = s.encode("ascii", "ignore").decode("ascii")
        s = re.sub(r"[^\w\s-]", "", s)
        return re.sub(r"[\s-]+", "_", s).strip("_") or "company"

    def fetch_jobs(self, base_url: str, html_src=None) -> list[dict]:
        if hasattr(self, "_jobs") and getattr(self, "_base_url_cache", None) == base_url:
            return self._jobs

        html = html_src if html_src else _rendered_html(base_url, timeout_ms=getattr(self, "_timeout", 30) * 1000)

        def _make_prompt(page_url, page_html):
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

        def _valid_url(raw, base):
            if not raw:
                return None
            if raw.startswith("/"):
                return urljoin(base, raw)
            if raw.startswith("http://") or raw.startswith("https://"):
                return raw
            return None

        timeout_ms = getattr(self, "_timeout", 30) * 1000
        all_jobs: list[dict] = []
        top_company = ""
        visited: set[str] = set()
        current_url = base_url
        current_html = html_src  # pasted HTML only used for the first page

        while current_url and current_url not in visited:
            visited.add(current_url)
            page_html = current_html if current_html else _rendered_html(current_url, timeout_ms=timeout_ms)
            current_html = None  # subsequent pages always fetched

            response = self._openai_client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": _make_prompt(current_url, page_html)}],
                temperature=0,
                seed=42,
                timeout=getattr(self, "_openai_timeout", 120),
            )
            data = json.loads(response.choices[0].message.content)
            log.debug("fetch_jobs page=%s response:\n%s", current_url, json.dumps(data, indent=2, ensure_ascii=False))

            if not top_company:
                top_company = data.get("company", "")

            for job in data.get("jobs", []):
                resolved = _valid_url(job.get("url", ""), current_url)
                if resolved:
                    all_jobs.append({**job, "url": resolved, "company": job.get("company") or top_company})

            next_page = _valid_url(data.get("next_page", ""), current_url)
            current_url = next_page if next_page and next_page != current_url else None

        self._jobs = all_jobs
        self._base_url_cache = base_url
        return self._jobs


if __name__ == "__main__":
    GenericScraper().run()
