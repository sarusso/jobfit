#!/usr/bin/env python3
"""
base_scraper.py — Abstract base class for job board scrapers.

Subclasses must implement:
    get_base_url(args)               — derive the board URL from parsed CLI args
    get_company_name(args)           — return the company slug/name for the data folder
    fetch_categories(base_url)       — return available category names
    fetch_links(base_url, allowed)   — return job URLs, filtered by allowed categories

Each run always saves a PDF per job to data/<company>/<role_id>.pdf.
If OPENAI_KEY is set in config.env, a JSON analysis is saved alongside it.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

_CONFIG_FILE = Path(__file__).parent / "config.env"


def _load_config() -> dict[str, str]:
    """Parse config.env (KEY=VALUE lines, # comments ignored)."""
    config: dict[str, str] = {}
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip()
    return config


class BaseScraper(ABC):

    # ------------------------------------------------------------------ #
    # Subclass interface                                                   #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def get_base_url(self, args: argparse.Namespace) -> str:
        """Derive the job board URL from parsed CLI arguments."""

    @abstractmethod
    def get_company_name(self, args: argparse.Namespace) -> str:
        """Return the company name used as the data subfolder."""

    @abstractmethod
    def fetch_categories(self, base_url: str) -> list[str]:
        """Return the list of category/section names available on the board."""

    @abstractmethod
    def fetch_links(self, base_url: str, allowed_categories: Optional[list[str]]) -> list[str]:
        """Return job URLs, optionally restricted to allowed_categories."""

    # ------------------------------------------------------------------ #
    # Category prompting (common)                                          #
    # ------------------------------------------------------------------ #

    def _prompt_categories(self, categories: list[str]) -> Optional[list[str]]:
        """Interactively ask the user which categories to include."""
        if not categories:
            print("No sections found on page — including all links.")
            return None

        print("\nAvailable sections:")
        for i, cat in enumerate(categories, start=1):
            print(f"  {i}. {cat}")

        raw = input(
            "\nEnter section numbers to include (comma-separated), or press Enter for all: "
        ).strip()

        if not raw:
            return None

        chosen_indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
        allowed = [categories[i] for i in chosen_indices if 0 <= i < len(categories)]

        if allowed:
            print(f"Filtering by: {', '.join(allowed)}")
            return allowed

        print("No valid selection — including all sections.")
        return None

    # ------------------------------------------------------------------ #
    # Common helpers                                                       #
    # ------------------------------------------------------------------ #

    def render_to_pdf(self, url: str, output_path: Path, page) -> str:
        """Navigate to url, save full page as PDF, return page plain text."""
        page.goto(url, wait_until="networkidle")
        page.pdf(path=str(output_path), format="A4", print_background=True)
        return page.inner_text("body")

    def analyse_job(self, text: str, url: str) -> dict:
        """Call OpenAI to extract structured job info from page plain text."""
        schema = {
            "title": "job title",
            "company": "company name",
            "location": "location or 'Remote'",
            "employment_type": "full-time | part-time | contract | internship | other",
            "experience_level": "junior | mid | senior | lead | executive | unspecified",
            "summary": (
                "1-2 sentences describing the role from a global, domain-specific perspective. "
                "Use industry terminology. Do NOT mention the company name or company-specific context — "
                "describe the role as a function (e.g. 'A senior backend engineering role focused on "
                "distributed systems and API design at scale.')."
            ),
            "company_description": "2-3 sentences describing what the company does, its market, and stage",
            "description": "COPY VERBATIM the full role description text as it appears above the responsibilities section. Do not summarise, truncate, or paraphrase.",
            "responsibilities": ["list of responsibilities"],
            "requirements": ["list of required qualifications / skills"],
            "nice_to_have": ["list of preferred but not required qualifications"],
            "salary": "salary info as a string, or null if not mentioned",
            "url": url,
        }
        prompt = (
            "Extract structured information from the following job posting and return ONLY valid JSON "
            "matching this schema (keep all field names exactly as shown):\n\n"
            f"{json.dumps(schema, indent=2)}\n\n"
            "Job posting text:\n\n"
            f"{text[:12000]}"
        )
        response = self._openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return json.loads(response.choices[0].message.content)

    def _save(self, url: str, pdf_src: Path, company: str, job: Optional[dict] = None) -> Path:
        """Save PDF (always) and JSON (when job is provided) to data/<company>/<role_id>.*
        Also writes data/<company>/_company.json on first analysis if not already present."""
        dest_dir = self._data_dir / company
        dest_dir.mkdir(parents=True, exist_ok=True)
        role_id = hashlib.sha256(url.encode()).hexdigest()
        shutil.copy2(pdf_src, dest_dir / f"{role_id}.pdf")
        if job is not None:
            job_data = {k: v for k, v in job.items() if k != "company_description"}
            with open(dest_dir / f"{role_id}.json", "w", encoding="utf-8") as f:
                json.dump(job_data, f, indent=2, ensure_ascii=False)
            company_file = dest_dir / "_company.json"
            if not company_file.exists() and job.get("company_description"):
                with open(company_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "company": job.get("company", company),
                        "description": job["company_description"],
                    }, f, indent=2, ensure_ascii=False)
        return dest_dir

    # ------------------------------------------------------------------ #
    # CLI                                                                  #
    # ------------------------------------------------------------------ #

    def build_arg_parser(self) -> argparse.ArgumentParser:
        """Return a parser with common arguments. Subclasses may extend it."""
        parser = argparse.ArgumentParser(
            description="Scrape job listings and save each as PDF (+ JSON if OPENAI_KEY is set)."
        )
        parser.add_argument(
            "-l", "--limit",
            type=int,
            default=None,
            help="Maximum number of links to process",
        )
        parser.add_argument(
            "-s", "--section",
            default=None,
            help="Comma-separated section numbers to include (e.g. -s 1 or -s 1,3). "
                 "Skips the interactive prompt.",
        )
        parser.add_argument(
            "--data-dir",
            default="data",
            help="Root folder for the job database (default: data/)",
        )
        return parser

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    def run(self, argv: Optional[list[str]] = None) -> None:
        args = self.build_arg_parser().parse_args(argv)

        self._data_dir = Path(args.data_dir)
        self._openai_client = None

        api_key = _load_config().get("OPENAI_KEY")
        if api_key:
            try:
                from openai import OpenAI
            except ImportError:
                print("WARNING: openai package not installed — JSON analysis disabled. Run: pip install openai")
            else:
                self._openai_client = OpenAI(api_key=api_key)

        base_url = self.get_base_url(args)
        company = self.get_company_name(args)
        print(f"Fetching links from: {base_url}")

        categories = self.fetch_categories(base_url)

        if args.section is not None:
            indices = [int(x.strip()) - 1 for x in args.section.split(",") if x.strip().isdigit()]
            allowed_categories = [categories[i] for i in indices if 0 <= i < len(categories)]
            if allowed_categories:
                print(f"Sections (from -s): {', '.join(allowed_categories)}")
            else:
                print("WARNING: -s produced no valid sections — including all.")
                allowed_categories = None
        else:
            allowed_categories = self._prompt_categories(categories)

        links = self.fetch_links(base_url, allowed_categories)
        if not links:
            print("No links matched. Exiting.")
            sys.exit(1)
        print(f"Found {len(links)} matching link(s).")

        if args.limit is not None:
            links = links[: args.limit]
            print(f"Limiting to {len(links)} link(s).")

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context()
            page = context.new_page()

            for i, url in enumerate(links, start=1):
                print(f"  [{i}/{len(links)}] {url}")
                try:
                    pdf_tmp = self._data_dir / f"_tmp_{i:04d}.pdf"
                    page_text = self.render_to_pdf(url, pdf_tmp, page)
                except Exception as e:
                    print(f"    WARNING: failed to render {url}: {e}")
                    continue

                job = None
                if self._openai_client:
                    try:
                        job = self.analyse_job(page_text, url)
                        print(f"    analysed: {job.get('title', '?')} @ {job.get('company', '?')}")
                    except Exception as e:
                        print(f"    WARNING: OpenAI analysis failed for {url}: {e}")

                dest = self._save(url, pdf_tmp, company, job)
                pdf_tmp.unlink()
                print(f"    saved → {dest}")

            context.close()
            browser.close()

        print("Done.")
