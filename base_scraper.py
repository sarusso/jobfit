#!/usr/bin/env python3
"""
base_scraper.py — Abstract base class for job board scrapers.

Subclasses must implement:
    get_base_url(args)       — derive the board URL from parsed CLI args
    get_company_name(args)   — return the company slug/name for the data folder
    fetch_jobs(base_url)     — return all jobs as [{title, url, category}]

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
    def fetch_jobs(self, base_url: str) -> list[dict]:
        """Return all jobs as a list of {title, url, category} dicts."""

    # Default convenience wrappers (backed by fetch_jobs)

    def fetch_categories(self, base_url: str) -> list[str]:
        seen: list[str] = []
        seen_set: set[str] = set()
        for job in self.fetch_jobs(base_url):
            c = job.get("category") or "General"
            if c not in seen_set:
                seen_set.add(c)
                seen.append(c)
        return seen

    def fetch_links(self, base_url: str, allowed_categories: Optional[list[str]]) -> list[str]:
        jobs = self.fetch_jobs(base_url)
        if allowed_categories:
            allowed = set(allowed_categories)
            jobs = [j for j in jobs if j.get("category") in allowed]
        seen: set[str] = set()
        urls: list[str] = []
        for j in jobs:
            u = j.get("url", "")
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
        return urls

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
        timeout_ms = getattr(self, "_timeout", 30) * 1000
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
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
            seed=42,
            timeout=getattr(self, "_openai_timeout", 120),
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
    # Web / programmatic interface                                         #
    # ------------------------------------------------------------------ #

    def setup(self, data_dir: Path, openai_client=None, timeout: int = 30, openai_timeout: int = 120) -> "BaseScraper":
        """Configure the scraper for use as a module (instead of via CLI)."""
        self._data_dir = data_dir
        self._openai_client = openai_client
        self._timeout = timeout
        self._openai_timeout = openai_timeout
        return self

    def scrape_iter(self, jobs: list[dict], company: Optional[str]):
        """Scrape a list of jobs [{url, title?, ...}] and yield progress dicts.

        company: fixed directory name for all jobs, or None to derive it from
                 each job's extracted company name (per-job auto-detect mode).
        Call setup() first."""
        import re
        import tempfile
        import unicodedata

        def _slugify(name: str) -> str:
            s = unicodedata.normalize("NFKD", name.lower())
            s = s.encode("ascii", "ignore").decode("ascii")
            s = re.sub(r"[^\w\s-]", "", s)
            return re.sub(r"[\s-]+", "_", s).strip("_") or "company"

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context()
            page = context.new_page()
            for i, job_stub in enumerate(jobs, 1):
                url = job_stub.get("url", "")
                event: dict = {"current": i, "url": url, "title": job_stub.get("title") or url}
                yield {**event, "starting": True}
                try:
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        pdf_tmp = Path(tmp.name)
                    page_text = self.render_to_pdf(url, pdf_tmp, page)
                    job = None
                    if self._openai_client:
                        try:
                            job = self.analyse_job(page_text, url)
                            event["title"] = job.get("title") or event["title"]
                        except Exception as e:
                            event["analyse_error"] = str(e)
                    # Resolve company directory: fixed > JD analysis > pre-fetched stub > URL hostname
                    if company:
                        dest_company = company
                    elif job and job.get("company"):
                        dest_company = _slugify(job["company"])
                    elif job_stub.get("company"):
                        dest_company = _slugify(job_stub["company"])
                    else:
                        dest_company = "unknown"
                    event["company"] = dest_company
                    self._save(url, pdf_tmp, dest_company, job)
                    pdf_tmp.unlink(missing_ok=True)
                except Exception as e:
                    event["error"] = str(e)
                yield event
            context.close()
            browser.close()

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
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Page load timeout in seconds (default: 30)",
        )
        parser.add_argument(
            "--openai-timeout",
            type=int,
            default=120,
            help="OpenAI request timeout in seconds (default: 120)",
        )
        return parser

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    def run(self, argv: Optional[list[str]] = None) -> None:
        args = self.build_arg_parser().parse_args(argv)

        self._data_dir = Path(args.data_dir)
        self._timeout = args.timeout
        self._openai_timeout = args.openai_timeout
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
        company  = self.get_company_name(args)
        print(f"Fetching jobs from: {base_url}")

        all_jobs   = self.fetch_jobs(base_url)
        categories = list(dict.fromkeys(j.get("category") or "General" for j in all_jobs))

        if args.section is not None:
            indices = [int(x.strip()) - 1 for x in args.section.split(",") if x.strip().isdigit()]
            allowed_set = {categories[i] for i in indices if 0 <= i < len(categories)}
            if allowed_set:
                print(f"Sections (from -s): {', '.join(sorted(allowed_set))}")
            else:
                print("WARNING: -s produced no valid sections — including all.")
                allowed_set = set()
        else:
            chosen = self._prompt_categories(categories)
            allowed_set = set(chosen) if chosen else set()

        jobs = [j for j in all_jobs if not allowed_set or j.get("category") in allowed_set]
        if not jobs:
            print("No links matched. Exiting.")
            sys.exit(1)
        print(f"Found {len(jobs)} matching job(s).")

        if args.limit is not None:
            jobs = jobs[: args.limit]
            print(f"Limiting to {len(jobs)} job(s).")

        for event in self.scrape_iter(jobs, company):
            i, total = event["current"], len(jobs)
            title = event.get("title") or event.get("url", "")
            if event.get("error"):
                print(f"  [{i}/{total}] ERROR: {event['error']} — {title}")
            else:
                print(f"  [{i}/{total}] {title}")

        print("Done.")
