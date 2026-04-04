#!/usr/bin/env python3
"""
app.py — Minimal Flask frontend for browsing the job database under data/.
"""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", category=Warning, module="urllib3")

import base64
import hashlib
import io
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, abort, redirect, render_template, request, send_file, session, stream_with_context, url_for

DATA_DIR    = Path(__file__).parent / "data"
CV_PATH     = DATA_DIR / "_cv.pdf"
NOTES_PATH  = DATA_DIR / "_notes.txt"
CONFIG_FILE = Path(__file__).parent / "config.env"

app = Flask(__name__)
app.secret_key = "jobscraper-local"
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("jobscraper")

SCORE_TIMEOUT = 60   # seconds per OpenAI call
MAX_RETRIES   = 3


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _load_config() -> dict[str, str]:
    config: dict[str, str] = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip()
    return config


def _openai_client():
    api_key = _load_config().get("OPENAI_KEY")
    if not api_key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=api_key)


def _cv_hash() -> str | None:
    if not CV_PATH.exists():
        return None
    return hashlib.sha256(CV_PATH.read_bytes()).hexdigest()


def _current_mode() -> str:
    return session.get("scoring_mode", "normal")


def _score_path(company: str, role_id: str, mode: str) -> Path:
    return DATA_DIR / company / "_scores" / f"{role_id}_{mode}.json"


def _load_score(company: str, role_id: str, mode: str | None = None) -> dict | None:
    if mode is None:
        mode = _current_mode()
    path = _score_path(company, role_id, mode)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("cv_hash") != _cv_hash():
        return None  # stale — CV has changed
    return data


def _save_score(company: str, role_id: str, score_data: dict, mode: str) -> None:
    path = _score_path(company, role_id, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    score_data["mode"] = mode
    with open(path, "w", encoding="utf-8") as f:
        json.dump(score_data, f, indent=2, ensure_ascii=False)


_PROMPT_CV_INFERENCE = (
    "IMPORTANT — how to read a CV:\n"
    "CVs are high-level summaries, not exhaustive technical inventories. "
    "A single bullet point may represent years of deep work. "
    "You MUST make reasonable professional inferences: if an entry clearly implies relevant "
    "experience (e.g. 'built a container-based HPC platform' implies distributed systems and "
    "microservices; 'led ML infrastructure' implies MLOps/GPU workloads), treat that experience "
    "as present. Do NOT penalise for the absence of an explicit keyword when the underlying "
    "competence is clearly inferable from what is written. "
    "Only flag something as a gap when there is genuinely no evidence of it — direct or implied.\n\n"
)

_PROMPT_NORMAL = (
    "You are an expert recruiter and career advisor. "
    "Score how well the candidate's CV (attached) matches the job description below.\n\n"
    + _PROMPT_CV_INFERENCE +
    "Return ONLY valid JSON with exactly these fields:\n"
    '{\n'
    '  "score": <integer 1-10>,\n'
    '  "reasoning": "<2-3 sentence explanation>",\n'
    '  "strengths": ["<item>", ...],\n'
    '  "gaps": ["<item>", ...]\n'
    '}\n\n'
    "Scoring rubric — apply it precisely, do not cluster scores between 6 and 8:\n"
    "  10 — Near-perfect fit. Candidate exceeds all requirements. Very likely to receive an offer.\n"
    "   9 — Excellent fit. Meets all key requirements, only minor gaps.\n"
    "   8 — Strong fit. Meets most requirements; gaps are small and easily bridgeable.\n"
    "   7 — Good fit. Meets core requirements but has some notable gaps. Likely shortlist.\n"
    "   6 — Borderline. Could make the shortlist but not a standout. Maybe shortlist.\n"
    "   5 — Borderline negative. As likely to make the shortlist as not. Maybe shortlist.\n"
    "   4 — Below average. Significant gaps in key requirements. Unlikely to be shortlisted.\n"
    "   3 — Poor fit. Missing several critical requirements.\n"
    "   2 — Very poor fit. Fundamental mismatch.\n"
    "   1 — No meaningful match.\n\n"
)

_PROMPT_BRUTAL = (
    "You are a brutally honest senior recruiter with 20 years of experience. "
    "Your reputation depends on being accurate and conservative — you never inflate scores. "
    "Score how well the candidate's CV (attached) matches the job description below.\n\n"
    + _PROMPT_CV_INFERENCE +
    "ADDITIONAL RULES FOR BRUTAL MODE:\n"
    "- Domain mismatch is a hard penalty. If the candidate's core background is in a clearly different "
    "technical domain than the one the role requires, score 3 or below regardless of seniority or breadth.\n"
    "- Scores of 8+ should be rare and only awarded when the candidate is a near-textbook match.\n"
    "- When in doubt, score lower. A 6 is already a reasonable candidate. A 7 is genuinely strong.\n"
    "- Never award a score higher than what the weakest critical requirement gap permits.\n\n"
    "Return ONLY valid JSON with exactly these fields:\n"
    '{\n'
    '  "score": <integer 1-10>,\n'
    '  "reasoning": "<2-3 sentence explanation that explicitly addresses domain fit>",\n'
    '  "strengths": ["<item>", ...],\n'
    '  "gaps": ["<item>", ...]\n'
    '}\n\n'
    "Scoring rubric:\n"
    "  10 — Textbook fit. Candidate exceeds every requirement. Offer is almost certain.\n"
    "   9 — Excellent fit. Meets all key requirements with negligible gaps. Very strong shortlist.\n"
    "   8 — Strong fit. Meets most requirements; gaps are minor and quickly bridgeable.\n"
    "   7 — Good fit. Core domain matches, but notable gaps exist. Likely shortlist.\n"
    "   6 — Borderline. Partial domain match; missing some requirements. Maybe shortlist.\n"
    "   5 — Weak fit. Some relevant experience but meaningful gaps. Unlikely shortlist.\n"
    "   4 — Poor fit. Significant domain or skill gaps. Very unlikely to be shortlisted.\n"
    "   3 — Bad fit. Missing most critical requirements or wrong domain entirely.\n"
    "   2 — Very poor fit. Fundamental domain or seniority mismatch.\n"
    "   1 — No meaningful match.\n\n"
)


def _do_score(job: dict, client, mode: str = "normal") -> dict:
    title = job.get("title", "?")
    log.debug("Scoring '%s' [mode=%s] …", title, mode)
    cv_b64 = base64.standard_b64encode(CV_PATH.read_bytes()).decode()
    notes = NOTES_PATH.read_text(encoding="utf-8").strip() if NOTES_PATH.exists() else ""
    notes_section = (
        f"Additional context provided by the candidate (treat as authoritative):\n{notes}\n\n"
        if notes else ""
    )
    prompt = (_PROMPT_NORMAL if mode == "normal" else _PROMPT_BRUTAL) + notes_section + (
        "Job description (JSON):\n"
        + json.dumps({k: v for k, v in job.items() if not k.startswith("_")},
                     indent=2, ensure_ascii=False)
    )
    t0 = datetime.now()
    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "file", "file": {"filename": "cv.pdf",
                                          "file_data": f"data:application/pdf;base64,{cv_b64}"}},
            ],
        }],
        temperature=0,
        timeout=SCORE_TIMEOUT,
    )
    elapsed = (datetime.now() - t0).total_seconds()
    result = json.loads(response.choices[0].message.content)
    log.debug("Scored '%s' → %s/10 in %.1fs", title, result.get("score"), elapsed)
    return result


def _url_to_pdf_and_text(url: str) -> tuple[bytes, str]:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30_000)
        pdf_bytes = page.pdf(format="A4")
        page_text = page.inner_text("body")
        browser.close()
    return pdf_bytes, page_text


_JD_SCHEMA = {
    "title": "job title",
    "location": "location or 'Remote'",
    "employment_type": "full-time | part-time | contract | internship | other",
    "experience_level": "junior | mid | senior | lead | executive | unspecified",
    "summary": (
        "1-2 sentences describing the role from a global, domain-specific perspective. "
        "Use industry terminology. Do NOT mention the company name — "
        "describe the role as a function."
    ),
    "company_description": "2-3 sentences describing what the company does, its market, and stage",
    "description": "COPY VERBATIM the full role description text as it appears above the responsibilities section. Do not summarise, truncate, or paraphrase.",
    "responsibilities": ["list of responsibilities"],
    "requirements": ["list of required qualifications / skills"],
    "nice_to_have": ["list of preferred but not required qualifications"],
    "salary": "salary info as a string, or null if not mentioned",
}


def _analyse_jd(text: str, client, url: str = "") -> dict:
    schema = dict(_JD_SCHEMA)
    if url:
        schema["url"] = url
    prompt = (
        "Extract structured information from the following job posting and return ONLY valid JSON "
        "matching this schema (keep all field names exactly as shown):\n\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "Job posting text:\n\n"
        f"{text[:12000]}"
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        timeout=SCORE_TIMEOUT,
    )
    return json.loads(response.choices[0].message.content)


def _make_role_id(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s-]+", "_", slug).strip("_")
    return slug or "role"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _companies() -> list[dict]:
    mode = _current_mode()
    companies = []
    for company_dir in sorted(DATA_DIR.iterdir()):
        if not company_dir.is_dir() or company_dir.name.startswith("_"):
            continue
        jobs = []
        for json_file in sorted(company_dir.glob("*.json")):
            if json_file.name.startswith("_"):
                continue
            data = _load_json(json_file)
            data["_role_id"] = json_file.stem
            data["_has_pdf"] = json_file.with_suffix(".pdf").exists()
            data["_score"] = _load_score(company_dir.name, json_file.stem, mode)
            jobs.append(data)
        if jobs:
            info_path = company_dir / "_company.json"
            info = _load_json(info_path) if info_path.exists() else {}
            companies.append({"name": company_dir.name, "jobs": jobs, "info": info})
    return companies


def _get_job(company: str, role_id: str) -> dict:
    path = DATA_DIR / company / f"{role_id}.json"
    if not path.exists():
        abort(404)
    data = _load_json(path)
    data["_role_id"] = role_id
    data["_has_pdf"] = path.with_suffix(".pdf").exists()
    data["_score"] = _load_score(company, role_id)
    return data


def _company_names() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(
        d.name for d in DATA_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )


@app.context_processor
def inject_globals():
    return {
        "cv_uploaded": CV_PATH.exists(),
        "can_score": CV_PATH.exists() and bool(_load_config().get("OPENAI_KEY")),
        "scoring_mode": _current_mode(),
        "existing_companies": _company_names(),
        "candidate_notes": NOTES_PATH.read_text(encoding="utf-8").strip() if NOTES_PATH.exists() else "",
    }


@app.route("/notes/save", methods=["POST"])
def notes_save():
    notes = request.form.get("notes", "").strip()
    DATA_DIR.mkdir(exist_ok=True)
    NOTES_PATH.write_text(notes, encoding="utf-8")
    return redirect(request.referrer or url_for("index"))


# ------------------------------------------------------------------ #
# Routes — mode                                                        #
# ------------------------------------------------------------------ #

@app.route("/set-mode", methods=["POST"])
def set_mode():
    mode = request.form.get("mode", "normal")
    session["scoring_mode"] = mode if mode in ("normal", "brutal") else "normal"
    return redirect(request.referrer or url_for("index"))


# ------------------------------------------------------------------ #
# Routes — browsing                                                    #
# ------------------------------------------------------------------ #

@app.route("/help")
def help_page():
    return render_template("help.html")


@app.route("/")
def index():
    return render_template("index.html", companies=_companies())


@app.route("/<company>")
def company_view(company: str):
    company_dir = DATA_DIR / company
    if not company_dir.is_dir():
        abort(404)
    company_info_path = company_dir / "_company.json"
    company_info = _load_json(company_info_path) if company_info_path.exists() else {}
    mode = _current_mode()
    jobs = []
    for json_file in sorted(company_dir.glob("*.json")):
        if json_file.name.startswith("_"):
            continue
        data = _load_json(json_file)
        data["_role_id"] = json_file.stem
        data["_has_pdf"] = json_file.with_suffix(".pdf").exists()
        data["_score"] = _load_score(company, json_file.stem, mode)
        jobs.append(data)
    jobs.sort(key=lambda j: (j["_score"] or {}).get("score", 0), reverse=True)
    return render_template("company.html", company=company, jobs=jobs, company_info=company_info)


@app.route("/<company>/<role_id>")
def job_view(company: str, role_id: str):
    job = _get_job(company, role_id)
    return render_template("job.html", company=company, job=job)


@app.route("/<company>/<role_id>/pdf")
def job_pdf(company: str, role_id: str):
    path = DATA_DIR / company / f"{role_id}.pdf"
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="application/pdf")


# ------------------------------------------------------------------ #
# Routes — CV                                                          #
# ------------------------------------------------------------------ #

@app.route("/cv/upload", methods=["POST"])
def cv_upload():
    f = request.files.get("cv")
    if not f or not f.filename.lower().endswith(".pdf"):
        abort(400, "Please upload a PDF file.")
    DATA_DIR.mkdir(exist_ok=True)
    f.save(CV_PATH)
    return redirect(url_for("index"))


@app.route("/cv")
def cv_view():
    if not CV_PATH.exists():
        abort(404)
    return send_file(CV_PATH, mimetype="application/pdf")


# ------------------------------------------------------------------ #
# Routes — JD upload                                                   #
# ------------------------------------------------------------------ #

@app.route("/upload-jd", methods=["POST"])
def upload_jd():
    company_raw = request.form.get("company", "").strip()
    pdf_file    = request.files.get("jd_pdf")
    url         = request.form.get("jd_url", "").strip()

    if not company_raw:
        abort(400, "Company name is required.")
    if not pdf_file and not url:
        abort(400, "Provide either a PDF file or a URL.")

    client = _openai_client()
    if not client:
        abort(400, "OPENAI_KEY not set in config.env.")

    # Obtain plain text (and PDF bytes when available) for analysis
    pdf_bytes = None
    if pdf_file:
        fname = pdf_file.filename.lower()
        if fname.endswith(".pdf"):
            pdf_bytes = pdf_file.read()
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            jd_text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        elif fname.endswith(".txt"):
            jd_text = pdf_file.read().decode("utf-8", errors="replace").strip()
        else:
            abort(400, "Please upload a PDF or TXT file.")
    else:
        log.info("Rendering URL to PDF: %s", url)
        pdf_bytes, jd_text = _url_to_pdf_and_text(url)

    # Full structured extraction (same schema as the scraper)
    job_data = _analyse_jd(jd_text, client, url=url)
    job_data["company"] = company_raw          # always use the user-supplied name
    job_data["source"]  = "url" if url else "manual"
    company_description = job_data.pop("company_description", None)

    title = job_data.get("title", "Unknown Role")
    log.info("Extracted title: %r  company: %r", title, company_raw)

    # Build filesystem-safe company slug
    company = re.sub(r"[^\w\s-]", "", company_raw.lower())
    company = re.sub(r"[\s-]+", "_", company).strip("_") or "company"

    company_dir = DATA_DIR / company
    company_dir.mkdir(parents=True, exist_ok=True)

    # Build a unique role_id
    role_id = _make_role_id(title)
    base_id = role_id
    counter = 1
    while (company_dir / f"{role_id}.json").exists():
        role_id = f"{base_id}_{counter}"
        counter += 1

    # Save PDF (when available) and JSON
    if pdf_bytes:
        (company_dir / f"{role_id}.pdf").write_bytes(pdf_bytes)
    with open(company_dir / f"{role_id}.json", "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=2, ensure_ascii=False)

    # Bootstrap _company.json if absent
    info_path = company_dir / "_company.json"
    if not info_path.exists():
        info: dict = {"company": company_raw}
        if company_description:
            info["description"] = company_description
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)

    return redirect(url_for("job_view", company=company, role_id=role_id))


# ------------------------------------------------------------------ #
# Routes — scoring                                                     #
# ------------------------------------------------------------------ #

@app.route("/score/<company>/<role_id>", methods=["POST"])
def score_one(company: str, role_id: str):
    if not CV_PATH.exists():
        abort(400, "No CV uploaded.")
    client = _openai_client()
    if not client:
        abort(400, "OPENAI_KEY not set in config.env.")
    mode = _current_mode()
    job = _get_job(company, role_id)
    result = _do_score(job, client, mode)
    result["cv_hash"] = _cv_hash()
    _save_score(company, role_id, result, mode)
    return redirect(request.referrer or url_for("job_view", company=company, role_id=role_id))


@app.route("/delete/<company>/<role_id>", methods=["POST"])
def delete_job(company: str, role_id: str):
    base = DATA_DIR / company
    for ext in (".json", ".pdf"):
        p = base / f"{role_id}{ext}"
        if p.exists():
            p.unlink()
    scores_dir = base / "_scores"
    if scores_dir.is_dir():
        for f in scores_dir.glob(f"{role_id}_*.json"):
            f.unlink()
    # If company folder is now empty (only _company.json / _scores left), stay on company page
    return redirect(url_for("company_view", company=company))


@app.route("/score/<company>/clear", methods=["POST"])
def clear_scores(company: str):
    scores_dir = DATA_DIR / company / "_scores"
    if scores_dir.is_dir():
        for f in scores_dir.glob("*.json"):
            f.unlink()
    return redirect(url_for("company_view", company=company))


@app.route("/score/<company>/stream")
def score_company_stream(company: str):
    if not CV_PATH.exists():
        abort(400, "No CV uploaded.")
    client = _openai_client()
    if not client:
        abort(400, "OPENAI_KEY not set in config.env.")
    company_dir = DATA_DIR / company
    if not company_dir.is_dir():
        abort(404)
    mode = _current_mode()

    to_score = [
        f for f in sorted(company_dir.glob("*.json"))
        if not f.name.startswith("_") and _load_score(company, f.stem, mode) is None
    ]
    total = len(to_score)

    log.info("Starting batch score for '%s': %d job(s), mode=%s", company, total, mode)

    def generate():
        failed = 0
        for i, json_file in enumerate(to_score, 1):
            job = _load_json(json_file)
            title = job.get("title", "?")
            log.info("[%d/%d] %s", i, total, title)
            yield f"data: {json.dumps({'current': i, 'total': total, 'title': title})}\n\n"
            last_error = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    result = _do_score(job, client, mode)
                    result["cv_hash"] = _cv_hash()
                    _save_score(company, json_file.stem, result, mode)
                    last_error = None
                    break
                except Exception as e:
                    last_error = str(e)
                    log.warning("[%d/%d] attempt %d/%d failed for '%s': %s",
                                i, total, attempt, MAX_RETRIES, title, last_error)
                    if attempt < MAX_RETRIES:
                        yield f"data: {json.dumps({'current': i, 'total': total, 'title': title, 'retry': attempt, 'error': last_error})}\n\n"
            if last_error:
                failed += 1
                log.error("[%d/%d] gave up on '%s' after %d attempts", i, total, title, MAX_RETRIES)
                yield f"data: {json.dumps({'current': i, 'total': total, 'title': title, 'failed': True, 'error': last_error})}\n\n"
        log.info("Batch score done for '%s': %d scored, %d failed", company, total - failed, failed)
        yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(debug=True)
