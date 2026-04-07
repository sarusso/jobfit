#!/usr/bin/env python3
"""
lever_scraper.py — Scraper for Lever-hosted job boards.

Usage:
    python lever_scraper.py <company> [options]

Example:
    python lever_scraper.py acme --analyse
"""

import argparse
import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from base_scraper import BaseScraper

log = logging.getLogger(__name__)

_BASE_URL_TEMPLATE = "https://jobs.lever.co/{company}"
_LINK_PATTERN = re.compile(r"lever\.co/[^/]+/[0-9a-f-]+$")


class LeverScraper(BaseScraper):

    def build_arg_parser(self) -> argparse.ArgumentParser:
        parser = super().build_arg_parser()
        parser.add_argument("company", help="Company slug as it appears in the Lever URL")
        return parser

    def get_base_url(self, args: argparse.Namespace) -> str:
        return _BASE_URL_TEMPLATE.format(company=args.company)

    def get_company_name(self, args: argparse.Namespace) -> str:
        return args.company

    def fetch_jobs(self, base_url: str) -> list[dict]:
        log.debug("fetch_jobs: GET %s", base_url)
        soup = self._fetch_soup(base_url)
        self._soup = soup

        jobs: list[dict] = []
        seen: set[str] = set()
        current_category = "General"

        for element in soup.descendants:
            if not hasattr(element, "get"):
                continue
            classes = " ".join(element.get("class") or [])
            if "posting-category-title" in classes and "large-category-label" in classes:
                current_category = element.get_text(strip=True) or "General"
                continue
            # Match only posting-title links, not Apply buttons (which share the same UUID URL)
            if element.name == "a" and "posting-title" in classes and element.get("href"):
                href = element["href"]
                if _LINK_PATTERN.search(href) and href not in seen:
                    seen.add(href)
                    title_el = element.find(attrs={"data-qa": "posting-name"}) or element.find("h5")
                    title = title_el.get_text(strip=True) if title_el else element.get_text(strip=True)
                    jobs.append({"title": title or href, "url": href, "category": current_category})

        log.debug("fetch_jobs: found %d jobs: %s", len(jobs), [(j["title"], j["category"]) for j in jobs])
        return jobs

    # ------------------------------------------------------------------ #

    def _fetch_soup(self, url: str) -> BeautifulSoup:
        log.debug("_fetch_soup: GET %s", url)
        resp = requests.get(url, timeout=getattr(self, "_timeout", 30))
        log.debug("_fetch_soup: status=%s len=%d", resp.status_code, len(resp.text))
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")


if __name__ == "__main__":
    LeverScraper().run()
