#!/usr/bin/env python3
"""
generic_scraper.py — LLM-assisted scraper for arbitrary job board pages.

Uses Playwright to get the fully-rendered DOM, strips non-content tags,
then asks gpt-4o-mini to extract job listings and categories.

Usage (CLI):
    python generic_scraper.py <careers_url> <company_name> [--limit N]
"""

import json
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from base_scraper import BaseScraper

_MAX_HTML_CHARS = 80_000


def _rendered_html(url: str) -> str:
    """Fetch fully-rendered DOM via Playwright and return cleaned HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30_000)
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
        slug = re.sub(r"[^\w\s-]", "", args.company.lower())
        return re.sub(r"[\s-]+", "_", slug).strip("_") or "company"

    def fetch_categories(self, base_url: str) -> list[str]:
        html = _rendered_html(base_url)

        prompt = (
            "You are analyzing the rendered HTML of a company careers/jobs page.\n\n"
            f"Page URL: {base_url}\n\n"
            "HTML (scripts, styles and non-essential attributes removed):\n"
            f"{html}\n\n"
            "Extract every individual job posting linked on this page.\n"
            "Return ONLY valid JSON:\n"
            "{\n"
            '  "categories": ["list of unique department or category names"],\n'
            '  "jobs": [\n'
            '    {"title": "Job Title", "url": "<href value>", "category": "Department"}\n'
            '  ]\n'
            "}\n\n"
            "Rules:\n"
            "- Only include <a href> links that point to individual job postings\n"
            "- Use the href value exactly as it appears in the HTML\n"
            "- If no departments are labelled, use 'General' for every job\n"
            "- Return empty lists if no jobs are found"
        )

        response = self._openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            timeout=60,
        )
        data = json.loads(response.choices[0].message.content)

        self._jobs = [
            {**job, "url": urljoin(base_url, job["url"])}
            for job in data.get("jobs", [])
            if job.get("url")
        ]
        self._base_url_cache = base_url
        return data.get("categories", [])

    def fetch_links(self, base_url: str, allowed_categories: Optional[list[str]]) -> list[str]:
        if not hasattr(self, "_jobs") or getattr(self, "_base_url_cache", None) != base_url:
            self.fetch_categories(base_url)

        jobs = self._jobs
        if allowed_categories:
            allowed = set(allowed_categories)
            jobs = [j for j in jobs if j.get("category") in allowed]

        seen: set[str] = set()
        urls: list[str] = []
        for job in jobs:
            url = job.get("url", "")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls


if __name__ == "__main__":
    GenericScraper().run()
