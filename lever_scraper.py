#!/usr/bin/env python3
"""
lever_scraper.py — Scraper for Lever-hosted job boards.

Usage:
    python lever_scraper.py <company> [options]

Example:
    python lever_scraper.py acme --analyse
"""

import argparse
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from base_scraper import BaseScraper

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

    def fetch_categories(self, base_url: str) -> list[str]:
        soup = self._fetch_soup(base_url)
        self._soup = soup  # cache for fetch_links
        return [
            tag.get_text(strip=True)
            for tag in soup.find_all(class_="posting-category-title large-category-label")
        ]

    def fetch_links(self, base_url: str, allowed_categories: Optional[list[str]]) -> list[str]:
        soup = self._soup
        seen: set[str] = set()
        links: list[str] = []

        if allowed_categories is None:
            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                if _LINK_PATTERN.search(href) and href not in seen:
                    seen.add(href)
                    links.append(href)
            return links

        allowed_set = set(allowed_categories)
        in_section = False

        for element in soup.descendants:
            if getattr(element, "get", None) and "posting-category-title" in " ".join(
                element.get("class", [])
            ) and "large-category-label" in " ".join(element.get("class", [])):
                in_section = element.get_text(strip=True) in allowed_set
                continue

            if in_section and getattr(element, "name", None) == "a" and element.get("href"):
                href = element["href"]
                if _LINK_PATTERN.search(href) and href not in seen:
                    seen.add(href)
                    links.append(href)

        return links

    # ------------------------------------------------------------------ #

    def _fetch_soup(self, url: str) -> BeautifulSoup:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")


if __name__ == "__main__":
    LeverScraper().run()
