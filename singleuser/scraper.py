#!/usr/bin/env python3
"""
scraper.py — Fetch all links matching a pattern from a base URL,
save each as a PDF, then merge into a single output PDF.
Optionally analyse each job via OpenAI and store results in
data/<company_name>/<role_id>.json.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter


def fetch_soup(base_url: str) -> "BeautifulSoup":
    """Fetch the base URL and return a parsed BeautifulSoup object."""
    resp = requests.get(base_url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def fetch_categories(soup: "BeautifulSoup") -> list[str]:
    """Return the list of section category names found on the page."""
    return [
        tag.get_text(strip=True)
        for tag in soup.find_all(class_="posting-category-title large-category-label")
    ]


def fetch_matching_links(
    soup: "BeautifulSoup",
    pattern: str,
    allowed_categories: Optional[list[str]] = None,
) -> list[str]:
    """Return unique hrefs matching pattern, optionally limited to allowed_categories."""
    regex = re.compile(pattern)
    seen: set[str] = set()
    links: list[str] = []

    if allowed_categories is None:
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            if regex.search(href) and href not in seen:
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
            if regex.search(href) and href not in seen:
                seen.add(href)
                links.append(href)

    return links


def extract_section(html: str, start_text: str, end_text: str) -> Optional[str]:
    """Return the HTML slice between start_text and end_text, or None if not found."""
    start_idx = html.find(start_text)
    end_idx = html.find(end_text)
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return None
    return html[start_idx + len(start_text):end_idx]


def render_to_pdf(url: str, output_path: Path, page) -> str:
    """Navigate to url, save full page as PDF, return page plain text."""
    page.goto(url, wait_until="networkidle")
    page.pdf(path=str(output_path), format="A4", print_background=True)
    return page.inner_text("body")


def analyse_job(text: str, url: str, client) -> dict:
    """Call OpenAI to extract structured job info from page plain text."""
    schema = {
        "title": "job title",
        "company": "company name",
        "location": "location or 'Remote'",
        "employment_type": "full-time | part-time | contract | internship | other",
        "experience_level": "junior | mid | senior | lead | executive | unspecified",
        "summary": "2-3 sentences covering what the company does",
        "description": "Role description in its entirety, exactly as it appears above the responsibilities or requirements.",
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
        "Do not cut paragraphs when extracting them. Job posting text:\n\n"
        f"{text[:12000]}"  # stay well within context limits
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        seed=42,
    )
    return json.loads(response.choices[0].message.content)


def save_job(job: dict, url: str, data_dir: Path) -> Path:
    """Persist a job dict to data_dir/<company>/<role_id>.json."""
    company = re.sub(r"[^\w\-]", "_", job.get("company", "unknown")).strip("_") or "unknown"
    role_id = hashlib.sha256(url.encode()).hexdigest()
    dest = data_dir / company / f"{role_id}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2, ensure_ascii=False)
    return dest


def merge_pdfs(pdf_paths: list[Path], output_path: Path) -> None:
    """Merge a list of PDF files into a single PDF."""
    writer = PdfWriter()
    for path in pdf_paths:
        writer.append(str(path))
    with open(output_path, "wb") as f:
        writer.write(f)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape links from a base URL, save each as PDF, merge into one file."
    )
    parser.add_argument("base_url", help="URL to scrape for links")
    parser.add_argument(
        "pattern",
        help="Regex pattern that matching links must satisfy (matched against href)",
    )
    parser.add_argument(
        "-o", "--output",
        default="output.pdf",
        help="Output merged PDF filename (default: output.pdf)",
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=None,
        help="Maximum number of links to process",
    )
    parser.add_argument(
        "--analyse",
        action="store_true",
        help="Analyse each job via OpenAI and save structured JSON alongside the PDF",
    )
    parser.add_argument(
        "--openai-key",
        default=None,
        help="OpenAI API key (defaults to OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root folder for the job database (default: data/)",
    )
    args = parser.parse_args()

    openai_client = None
    if args.analyse:
        try:
            from openai import OpenAI
        except ImportError:
            print("ERROR: openai package not installed. Run: pip install openai")
            sys.exit(1)
        api_key = args.openai_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("ERROR: OpenAI API key required. Use --openai-key or set OPENAI_API_KEY.")
            sys.exit(1)
        openai_client = OpenAI(api_key=api_key)

    print(f"Fetching links from: {args.base_url}")
    soup = fetch_soup(args.base_url)

    # --- category filtering ---
    categories = fetch_categories(soup)
    allowed_categories: Optional[list[str]] = None
    if categories:
        print("\nAvailable sections:")
        for i, cat in enumerate(categories, start=1):
            print(f"  {i}. {cat}")
        raw = input(
            "\nEnter section numbers to include (comma-separated), or press Enter for all: "
        ).strip()
        if raw:
            chosen_indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
            allowed_categories = [categories[i] for i in chosen_indices if 0 <= i < len(categories)]
            if allowed_categories:
                print(f"Filtering by: {', '.join(allowed_categories)}")
            else:
                print("No valid selection — including all sections.")
                allowed_categories = None
    else:
        print("No sections found on page — including all links.")

    links = fetch_matching_links(soup, args.pattern, allowed_categories)
    if not links:
        print("No links matched the pattern. Exiting.")
        sys.exit(1)
    print(f"Found {len(links)} matching link(s).")
    if args.limit is not None:
        links = links[: args.limit]
        print(f"Limiting to {len(links)} link(s).")

    output_path = Path(args.output)
    data_dir = Path(args.data_dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        pdf_paths = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context()
            page = context.new_page()

            for i, url in enumerate(links, start=1):
                pdf_file = tmp / f"page_{i:04d}.pdf"
                print(f"  [{i}/{len(links)}] {url}")
                try:
                    page_text = render_to_pdf(url, pdf_file, page)
                    pdf_paths.append(pdf_file)
                except Exception as e:
                    print(f"    WARNING: failed to render {url}: {e}")
                    continue

                if openai_client:
                    try:
                        job = analyse_job(page_text, url, openai_client)
                        dest = save_job(job, url, data_dir)
                        print(f"    analysed: {job.get('title', '?')} @ {job.get('company', '?')} → {dest}")
                    except Exception as e:
                        print(f"    WARNING: OpenAI analysis failed for {url}: {e}")

            context.close()
            browser.close()

        if not pdf_paths:
            print("No PDFs were generated. Exiting.")
            sys.exit(1)

        print(f"Merging {len(pdf_paths)} PDF(s) into {output_path} ...")
        merge_pdfs(pdf_paths, output_path)

    print(f"Done. Output: {output_path}")


if __name__ == "__main__":
    main()
