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

from flask import Flask, Response, abort, flash, redirect, render_template, request, send_file, session, stream_with_context, url_for

DATA_DIR        = Path(__file__).parent / "data"
CVS_DIR         = DATA_DIR / "_cvs"
CV_INDEX_PATH   = CVS_DIR / "_index.json"
_LEGACY_CV_PATH = DATA_DIR / "_cv.pdf"   # migration only
NOTES_PATH      = DATA_DIR / "_notes.txt"
CONFIG_FILE     = Path(__file__).parent / "config.env"

app = Flask(__name__)
app.secret_key = "jobscraper-local"
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB

# Server-side store for scrape sessions (avoids cookie-size limits)
_scrape_sessions: dict[str, dict] = {}

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


def _cv_index() -> dict:
    """Load CV index, auto-migrating legacy _cv.pdf if present."""
    if not CV_INDEX_PATH.exists():
        if _LEGACY_CV_PATH.exists():
            pdf_bytes = _LEGACY_CV_PATH.read_bytes()
            h = hashlib.sha256(pdf_bytes).hexdigest()
            CVS_DIR.mkdir(parents=True, exist_ok=True)
            dest = CVS_DIR / f"{h}.pdf"
            if not dest.exists():
                dest.write_bytes(pdf_bytes)
            index: dict = {"selected": h, "cvs": {h: {"name": "CV", "uploaded": datetime.now().isoformat()}}}
            with open(CV_INDEX_PATH, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2)
            _LEGACY_CV_PATH.unlink()
            return index
        return {"selected": None, "cvs": {}}
    with open(CV_INDEX_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_cv_index(index: dict) -> None:
    CVS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CV_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def _selected_cv_path() -> Path | None:
    idx = _cv_index()
    h = idx.get("selected")
    if not h:
        return None
    p = CVS_DIR / f"{h}.pdf"
    return p if p.exists() else None


def _cv_hash() -> str | None:
    """Return the SHA-256 hash of the selected CV (it's the filename stem)."""
    p = _selected_cv_path()
    return p.stem if p else None


def _all_cvs() -> list[dict]:
    idx = _cv_index()
    result = []
    for h, meta in idx.get("cvs", {}).items():
        p = CVS_DIR / f"{h}.pdf"
        if not p.exists():
            continue
        try:
            uploaded_str = datetime.fromisoformat(meta.get("uploaded", "")).strftime("%-d %B %Y, %H:%M")
        except Exception:
            uploaded_str = "Unknown"
        result.append({
            "hash": h,
            "name": meta.get("name", "CV"),
            "uploaded": uploaded_str,
            "uploaded_ts": meta.get("uploaded", ""),
            "selected": h == idx.get("selected"),
        })
    result.sort(key=lambda x: x["uploaded_ts"], reverse=True)
    return result


def _current_mode() -> str:
    return session.get("scoring_mode", "normal")


def _use_notes() -> bool:
    return session.get("use_notes", False)


def _score_path(company: str, role_id: str, mode: str, use_notes: bool = False, cv_hash: str | None = None) -> Path:
    h8 = (cv_hash or _cv_hash() or "nocv")[:8]
    suffix = f"{mode}_notes_{h8}" if use_notes else f"{mode}_{h8}"
    return DATA_DIR / company / "_scores" / f"{role_id}_{suffix}.json"


def _load_score(company: str, role_id: str, mode: str | None = None, use_notes: bool | None = None) -> dict | None:
    if mode is None:
        mode = _current_mode()
    if use_notes is None:
        use_notes = _use_notes()
    path = _score_path(company, role_id, mode, use_notes)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("cv_hash") != _cv_hash():
        return None  # stale — CV has changed
    return data


def _save_score(company: str, role_id: str, score_data: dict, mode: str, use_notes: bool = False) -> None:
    path = _score_path(company, role_id, mode, use_notes)
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


def _do_score(job: dict, client, mode: str = "normal", use_notes: bool = False) -> dict:
    title = job.get("title", "?")
    log.debug("Scoring '%s' [mode=%s, notes=%s] …", title, mode, use_notes)
    cv_path = _selected_cv_path()
    cv_b64 = base64.standard_b64encode(cv_path.read_bytes()).decode()
    notes = NOTES_PATH.read_text(encoding="utf-8").strip() if (use_notes and NOTES_PATH.exists()) else ""
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
        seed=42,
        timeout=SCORE_TIMEOUT,
    )
    elapsed = (datetime.now() - t0).total_seconds()
    result = json.loads(response.choices[0].message.content)
    result["cv_hash"] = _cv_hash()
    if notes:
        result["notes_used"] = notes
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
    "company": "company name as it appears in the posting — leave empty string if not clearly stated",
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
        seed=42,
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
    use_notes = _use_notes()
    mode = _current_mode()
    data["_score"] = _load_score(company, role_id, mode, use_notes)
    delta = None
    if use_notes and data["_score"]:
        plain = _load_score(company, role_id, mode, use_notes=False)
        if plain is not None:
            delta = data["_score"]["score"] - plain["score"]
    data["_score_delta"] = delta
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
    cv_path = _selected_cv_path()
    return {
        "cv_uploaded": cv_path is not None,
        "all_cvs": _all_cvs(),
        "has_openai_key": bool(_load_config().get("OPENAI_KEY")),
        "can_score": cv_path is not None and bool(_load_config().get("OPENAI_KEY")),
        "scoring_mode": _current_mode(),
        "use_notes": _use_notes(),
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


@app.route("/set-notes", methods=["POST"])
def set_notes_mode():
    session["use_notes"] = request.form.get("use_notes") == "1"
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
    pdf_bytes = f.read()
    h = hashlib.sha256(pdf_bytes + f.filename.encode()).hexdigest()
    CVS_DIR.mkdir(parents=True, exist_ok=True)
    idx = _cv_index()
    if h in idx.get("cvs", {}):
        flash("This CV has already been uploaded.", "warning")
        return _modal_cv_redirect()
    (CVS_DIR / f"{h}.pdf").write_bytes(pdf_bytes)
    name = Path(f.filename).stem.replace("_", " ").replace("-", " ").strip() or "CV"
    idx.setdefault("cvs", {})[h] = {"name": name, "uploaded": datetime.now().isoformat()}
    idx["selected"] = h
    _save_cv_index(idx)
    return _modal_cv_redirect()


def _modal_cv_redirect():
    ref = request.referrer or url_for("index")
    return redirect(ref.split("?")[0] + "?modal=cv")


@app.route("/cv/select/<cv_hash>", methods=["POST"])
def cv_select(cv_hash: str):
    idx = _cv_index()
    if cv_hash in idx.get("cvs", {}) and (CVS_DIR / f"{cv_hash}.pdf").exists():
        idx["selected"] = cv_hash
        _save_cv_index(idx)
    return _modal_cv_redirect()


@app.route("/cv/rename/<cv_hash>", methods=["POST"])
def cv_rename(cv_hash: str):
    name = request.form.get("name", "").strip() or "CV"
    idx = _cv_index()
    if cv_hash in idx.get("cvs", {}):
        idx["cvs"][cv_hash]["name"] = name
        _save_cv_index(idx)
    return redirect(request.referrer or url_for("index"))


@app.route("/cv/delete/<cv_hash>", methods=["POST"])
def cv_delete(cv_hash: str):
    idx = _cv_index()
    cvs = idx.get("cvs", {})
    if cv_hash in cvs:
        p = CVS_DIR / f"{cv_hash}.pdf"
        if p.exists():
            p.unlink()
        del cvs[cv_hash]
        if idx.get("selected") == cv_hash:
            idx["selected"] = next(iter(cvs), None)
        _save_cv_index(idx)
    return _modal_cv_redirect()


@app.route("/cv")
def cv_view():
    p = _selected_cv_path()
    if not p:
        abort(404)
    return send_file(p, mimetype="application/pdf")


@app.route("/cv/<cv_hash>")
def cv_view_specific(cv_hash: str):
    p = CVS_DIR / f"{cv_hash}.pdf"
    if not p.exists():
        abort(404)
    return send_file(p, mimetype="application/pdf")


# ------------------------------------------------------------------ #
# Routes — Add Jobs page                                               #
# ------------------------------------------------------------------ #

def _save_job(company_raw: str, job_data: dict, pdf_bytes: bytes | None = None) -> tuple[str, str]:
    """Persist a job to disk. Returns (company_slug, role_id)."""
    company_description = job_data.pop("company_description", None)
    title = job_data.get("title", "Unknown Role")
    log.info("Saving job: %r  company: %r", title, company_raw)

    company = re.sub(r"[^\w\s-]", "", company_raw.lower())
    company = re.sub(r"[\s-]+", "_", company).strip("_") or "unknown"
    company_dir = DATA_DIR / company
    company_dir.mkdir(parents=True, exist_ok=True)

    role_id = _make_role_id(title)
    base_id = role_id
    counter = 1
    while (company_dir / f"{role_id}.json").exists():
        role_id = f"{base_id}_{counter}"
        counter += 1

    if pdf_bytes:
        (company_dir / f"{role_id}.pdf").write_bytes(pdf_bytes)
    with open(company_dir / f"{role_id}.json", "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=2, ensure_ascii=False)

    info_path = company_dir / "_company.json"
    if not info_path.exists():
        info: dict = {"company": company_raw}
        if company_description:
            info["description"] = company_description
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)

    return company, role_id


@app.route("/add-jobs")
def add_jobs():
    return redirect(url_for("index") + "?modal=add-jobs")


@app.route("/add-jobs/url", methods=["POST"])
@app.route("/upload-jd", methods=["POST"])
def add_job_url():
    company_raw = request.form.get("company", "").strip()
    pdf_file    = request.files.get("jd_pdf")
    url         = request.form.get("jd_url", "").strip()

    if not pdf_file and not url:
        abort(400, "Provide either a PDF file or a URL.")

    client = _openai_client()
    if not client:
        abort(400, "OPENAI_KEY not set in config.env.")

    pdf_bytes = None
    if pdf_file:
        fname = pdf_file.filename.lower()
        if fname.endswith(".pdf"):
            pdf_bytes = pdf_file.read()
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            jd_text = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
        elif fname.endswith(".txt"):
            jd_text = pdf_file.read().decode("utf-8", errors="replace").strip()
        else:
            abort(400, "Please upload a PDF or TXT file.")
    else:
        log.info("Rendering URL to PDF: %s", url)
        pdf_bytes, jd_text = _url_to_pdf_and_text(url)

    job_data = _analyse_jd(jd_text, client, url=url)
    # User-supplied name takes precedence; fall back to LLM-extracted name
    resolved = company_raw or job_data.get("company", "").strip()
    if not resolved:
        abort(400, "Could not determine the company name. Please fill in the Company field.")
    job_data["company"] = resolved
    job_data["source"]  = "url" if url else "manual"
    company, role_id = _save_job(resolved, job_data, pdf_bytes)
    return redirect(url_for("job_view", company=company, role_id=role_id))


@app.route("/add-jobs/text", methods=["POST"])
def add_job_text():
    company_raw = request.form.get("company", "").strip()
    text        = request.form.get("text", "").strip()

    if not text:
        abort(400, "Job description text is required.")

    client = _openai_client()
    if not client:
        abort(400, "OPENAI_KEY not set in config.env.")

    job_data = _analyse_jd(text, client)
    resolved = company_raw or job_data.get("company", "").strip()
    if not resolved:
        abort(400, "Could not determine the company name. Please fill in the Company field.")
    job_data["company"] = resolved
    job_data["source"]  = "text"
    company, role_id = _save_job(resolved, job_data)
    return redirect(url_for("job_view", company=company, role_id=role_id))


@app.route("/add-jobs/scrape/categories", methods=["POST"])
def scrape_categories():
    data    = request.get_json(force=True) or {}
    board   = data.get("board", "lever")
    company = data.get("company", "").strip()
    url     = data.get("url", "").strip()

    if board == "lever":
        from lever_scraper import LeverScraper
        if not company:
            return json.dumps({"error": "Company slug is required."}), 400
        base_url = f"https://jobs.lever.co/{company}"
        try:
            jobs = LeverScraper().setup(DATA_DIR).fetch_jobs(base_url)
        except Exception as e:
            return json.dumps({"error": str(e)}), 500
    else:
        from generic_scraper import GenericScraper
        html_src = data.get("html_src", "").strip()
        if not url and not html_src:
            return json.dumps({"error": "Enter the careers page URL or paste HTML source."}), 400
        client = _openai_client()
        if not client:
            return json.dumps({"error": "OPENAI_KEY is required for generic scraping."}), 400
        base_url = url or "unknown"
        try:
            jobs = GenericScraper().setup(DATA_DIR, client).fetch_jobs(base_url, html_src=html_src or None)
        except Exception as e:
            return json.dumps({"error": str(e)}), 500

    return json.dumps({"jobs": jobs, "base_url": base_url})


@app.route("/add-jobs/scrape/confirm", methods=["POST"])
def scrape_confirm():
    import uuid
    data      = request.get_json(force=True) or {}
    scrape_id = str(uuid.uuid4())
    limit     = data.get("limit")
    jobs      = data.get("jobs") or []
    if limit:
        jobs = jobs[:int(limit)]
    _scrape_sessions[scrape_id] = {
        "board":          data.get("board", "lever"),
        "company":        data.get("company", ""),
        "jobs":           jobs,
        "timeout":        int(data.get("timeout") or 30),
        "openai_timeout": int(data.get("openai_timeout") or 120),
    }
    session["_scrape_id"] = scrape_id
    return json.dumps({"ok": True})


@app.route("/add-jobs/scrape/stream")
def scrape_stream():
    scrape_id = session.get("_scrape_id")
    params    = _scrape_sessions.pop(scrape_id, None) if scrape_id else None
    if not params:
        abort(400, "No scrape session.")

    board          = params.get("board", "lever")
    company_raw    = params.get("company", "").strip()
    jobs           = params.get("jobs", [])
    timeout        = params.get("timeout", 30)
    openai_timeout = params.get("openai_timeout", 120)
    client         = _openai_client()

    def _slugify(name: str) -> str:
        import unicodedata
        s = unicodedata.normalize("NFKD", name.lower())
        s = s.encode("ascii", "ignore").decode("ascii")
        s = re.sub(r"[^\w\s-]", "", s)
        return re.sub(r"[\s-]+", "_", s).strip("_") or "company"

    # Fixed company slug when user provided a name; None means per-job auto-detect
    fixed_company = _slugify(company_raw) if company_raw else None

    def generate():
        total = len(jobs)
        if not total:
            yield f"data: {json.dumps({'done': True, 'total': 0})}\n\n"
            return
        if board == "lever":
            from lever_scraper import LeverScraper
            scraper = LeverScraper().setup(DATA_DIR, client, timeout=timeout, openai_timeout=openai_timeout)
        else:
            from generic_scraper import GenericScraper
            scraper = GenericScraper().setup(DATA_DIR, client, timeout=timeout, openai_timeout=openai_timeout)
        last_company = fixed_company
        for event in scraper.scrape_iter(jobs, fixed_company):
            event["total"] = total
            if event.get("company"):
                last_company = event["company"]
            yield f"data: {json.dumps(event)}\n\n"
        done_payload: dict = {"done": True, "total": total}
        if fixed_company:
            done_payload["company"] = fixed_company
        elif last_company:
            done_payload["company"] = last_company
        yield f"data: {json.dumps(done_payload)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------ #
# Routes — scoring                                                     #
# ------------------------------------------------------------------ #

@app.route("/score/<company>/<role_id>", methods=["POST"])
def score_one(company: str, role_id: str):
    if not _selected_cv_path():
        abort(400, "No CV uploaded.")
    client = _openai_client()
    if not client:
        abort(400, "OPENAI_KEY not set in config.env.")
    mode = _current_mode()
    notes = _use_notes()
    job = _get_job(company, role_id)
    result = _do_score(job, client, mode, notes)
    result["cv_hash"] = _cv_hash()
    _save_score(company, role_id, result, mode, notes)
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
    if not _selected_cv_path():
        abort(400, "No CV uploaded.")
    client = _openai_client()
    if not client:
        abort(400, "OPENAI_KEY not set in config.env.")
    company_dir = DATA_DIR / company
    if not company_dir.is_dir():
        abort(404)
    mode = _current_mode()
    notes = _use_notes()

    to_score = [
        f for f in sorted(company_dir.glob("*.json"))
        if not f.name.startswith("_") and _load_score(company, f.stem, mode, notes) is None
    ]
    total = len(to_score)

    log.info("Starting batch score for '%s': %d job(s), mode=%s, notes=%s", company, total, mode, notes)

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
                    result = _do_score(job, client, mode, notes)
                    result["cv_hash"] = _cv_hash()
                    _save_score(company, json_file.stem, result, mode, notes)
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
