"""
jobs_views.py — Django port of the singleuser Flask app.

Data layout (per user):
    DATA_DIR/<username>/
        _cvs/_index.json
        _cvs/<hash>.pdf
        _notes.txt
        <company>/
            _company.json
            <role_id>.json
            <role_id>.pdf
            _scores/<role_id>_<mode>[_notes]_<h8>.json
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import (FileResponse, Http404, HttpResponse,
                         HttpResponseRedirect, JsonResponse,
                         StreamingHttpResponse)
from django.shortcuts import render
from django.urls import reverse

from .decorators import private_view

log = logging.getLogger(__name__)

SCORE_TIMEOUT = 60
MAX_RETRIES   = 3


# ------------------------------------------------------------------ #
# Per-user path helpers                                               #
# ------------------------------------------------------------------ #

def _data_dir(request) -> Path:
    return Path(settings.DATA_DIR) / request.user.username

def _cvs_dir(data_dir: Path) -> Path:
    return data_dir / "_cvs"

def _cv_index_path(data_dir: Path) -> Path:
    return _cvs_dir(data_dir) / "_index.json"

def _notes_path(data_dir: Path) -> Path:
    return data_dir / "_notes.txt"


# ------------------------------------------------------------------ #
# CV helpers                                                          #
# ------------------------------------------------------------------ #

def _cv_index(data_dir: Path) -> dict:
    p = _cv_index_path(data_dir)
    if not p.exists():
        return {"selected": None, "cvs": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_cv_index(data_dir: Path, index: dict) -> None:
    _cvs_dir(data_dir).mkdir(parents=True, exist_ok=True)
    with open(_cv_index_path(data_dir), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def _selected_cv_path(data_dir: Path):
    idx = _cv_index(data_dir)
    h = idx.get("selected")
    if not h:
        return None
    p = _cvs_dir(data_dir) / f"{h}.pdf"
    return p if p.exists() else None


def _cv_hash(data_dir: Path):
    p = _selected_cv_path(data_dir)
    return p.stem if p else None


def _all_cvs(data_dir: Path) -> list:
    idx = _cv_index(data_dir)
    result = []
    for h, meta in idx.get("cvs", {}).items():
        p = _cvs_dir(data_dir) / f"{h}.pdf"
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


# ------------------------------------------------------------------ #
# Score helpers                                                       #
# ------------------------------------------------------------------ #

def _current_mode(request) -> str:
    return request.session.get("scoring_mode", "normal")


def _use_notes(request) -> bool:
    return request.session.get("use_notes", False)


def _score_path(data_dir: Path, company: str, role_id: str, mode: str,
                use_notes: bool = False, cv_hash: str | None = None) -> Path:
    h8 = (cv_hash or _cv_hash(data_dir) or "nocv")[:8]
    suffix = f"{mode}_notes_{h8}" if use_notes else f"{mode}_{h8}"
    return data_dir / company / "_scores" / f"{role_id}_{suffix}.json"


def _load_score(data_dir: Path, company: str, role_id: str,
                mode: str | None = None, use_notes: bool | None = None,
                cv_hash_override: str | None = None) -> dict | None:
    if mode is None:
        mode = "normal"
    if use_notes is None:
        use_notes = False
    cv_h = cv_hash_override or _cv_hash(data_dir)
    path = _score_path(data_dir, company, role_id, mode, use_notes, cv_h)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("cv_hash") != cv_h:
        return None
    return data


def _all_cv_scores(data_dir: Path, company: str, role_id: str) -> list:
    scores_dir = data_dir / company / "_scores"
    if not scores_dir.exists():
        return []
    idx = _cv_index(data_dir)
    h8_to_cv = {h[:8]: {"hash": h, "name": meta.get("name", "CV")}
                for h, meta in idx.get("cvs", {}).items()}
    results = []
    for path in sorted(scores_dir.glob(f"{role_id}_*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        cv_hash_full = data.get("cv_hash")
        h8 = cv_hash_full[:8] if cv_hash_full else None
        if not h8:
            stem = path.stem[len(role_id) + 1:]
            h8 = stem.split("_")[-1]
        cv_info = h8_to_cv.get(h8, {"hash": h8, "name": "Unknown CV"})
        use_notes = "_notes_" in path.stem
        results.append({
            "score": data.get("score"),
            "mode": data.get("mode", "normal"),
            "use_notes": use_notes,
            "cv_hash": cv_info["hash"],
            "cv_name": cv_info["name"],
            "reasoning": data.get("reasoning", ""),
        })
    results.sort(key=lambda x: (x["cv_name"], x["mode"], x["use_notes"]))
    return results


def _save_score(data_dir: Path, company: str, role_id: str,
                score_data: dict, mode: str, use_notes: bool = False) -> None:
    path = _score_path(data_dir, company, role_id, mode, use_notes)
    path.parent.mkdir(parents=True, exist_ok=True)
    score_data["mode"] = mode
    with open(path, "w", encoding="utf-8") as f:
        json.dump(score_data, f, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------ #
# OpenAI helpers                                                      #
# ------------------------------------------------------------------ #

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
    "Scoring rubric — apply it precisely:\n"
    "  10 — Near-perfect fit. Candidate exceeds all requirements.\n"
    "   9 — Excellent fit. Meets all key requirements, only minor gaps.\n"
    "   8 — Strong fit. Meets most requirements; gaps are small.\n"
    "   7 — Good fit. Meets core requirements but has notable gaps.\n"
    "   6 — Borderline. Could make the shortlist but not a standout.\n"
    "   5 — Borderline negative. As likely to make the shortlist as not.\n"
    "   4 — Below average. Significant gaps in key requirements.\n"
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
    "- Never award a score higher than what the weakest critical requirement gap permits.\n\n"
    "Return ONLY valid JSON with exactly these fields:\n"
    '{\n'
    '  "score": <integer 1-10>,\n'
    '  "reasoning": "<2-3 sentence explanation that explicitly addresses domain fit>",\n'
    '  "strengths": ["<item>", ...],\n'
    '  "gaps": ["<item>", ...]\n'
    '}\n\n'
    "Scoring rubric:\n"
    "  10 — Textbook fit. Offer is almost certain.\n"
    "   9 — Excellent fit. Very strong shortlist.\n"
    "   8 — Strong fit. Gaps are minor.\n"
    "   7 — Good fit. Notable gaps but likely shortlist.\n"
    "   6 — Borderline. Partial domain match.\n"
    "   5 — Weak fit. Unlikely shortlist.\n"
    "   4 — Poor fit. Very unlikely shortlisted.\n"
    "   3 — Bad fit. Wrong domain or missing critical requirements.\n"
    "   2 — Very poor fit.\n"
    "   1 — No meaningful match.\n\n"
)

_JD_SCHEMA = {
    "title": "job title",
    "company": "company name as it appears in the posting — leave empty string if not clearly stated",
    "location": "location or 'Remote'",
    "employment_type": "full-time | part-time | contract | internship | other",
    "experience_level": "junior | mid | senior | lead | executive | unspecified",
    "summary": (
        "1-2 sentences describing the role from a global, domain-specific perspective. "
        "Use industry terminology. Do NOT mention the company name."
    ),
    "company_description": "2-3 sentences describing what the company does",
    "description": "COPY VERBATIM the full role description text. Do not summarise or truncate.",
    "responsibilities": ["list of responsibilities"],
    "requirements": ["list of required qualifications / skills"],
    "nice_to_have": ["list of preferred but not required qualifications"],
    "salary": "salary info as a string, or null if not mentioned",
}


def _openai_client():
    api_key = settings.OPENAI_KEY
    if not api_key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=api_key)


def _do_score(data_dir: Path, job: dict, client, mode: str = "normal", use_notes: bool = False) -> dict:
    notes_path = _notes_path(data_dir)
    cv_path = _selected_cv_path(data_dir)
    cv_b64 = base64.standard_b64encode(cv_path.read_bytes()).decode()
    notes = notes_path.read_text(encoding="utf-8").strip() if (use_notes and notes_path.exists()) else ""
    notes_section = (
        f"Additional context provided by the candidate (treat as authoritative):\n{notes}\n\n"
        if notes else ""
    )
    prompt = (_PROMPT_NORMAL if mode == "normal" else _PROMPT_BRUTAL) + notes_section + (
        "Job description (JSON):\n"
        + json.dumps({k: v for k, v in job.items() if not k.startswith("_") and k not in
                      ("role_id", "has_pdf", "score", "score_delta", "all_scores", "added_at_display")},
                     indent=2, ensure_ascii=False)
    )
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
    result = json.loads(response.choices[0].message.content)
    result["cv_hash"] = _cv_hash(data_dir)
    result["scored_at"] = datetime.now().isoformat()
    if notes:
        result["notes_used"] = notes
    return result


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


def _url_to_pdf_and_text(url: str):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30_000)
        pdf_bytes = page.pdf(format="A4")
        page_text = page.inner_text("body")
        browser.close()
    return pdf_bytes, page_text


# ------------------------------------------------------------------ #
# Job/company data helpers                                            #
# ------------------------------------------------------------------ #

def _make_role_id(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s-]+", "_", slug).strip("_")
    return slug or "role"


def _slugify_company(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[\s-]+", "_", s).strip("_") or "unknown"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _set_archived(path: Path, archived: bool) -> None:
    data = _load_json(path) if path.exists() else {}
    if archived:
        data["archived"] = True
    else:
        data.pop("archived", None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _get_companies(data_dir: Path, mode: str, use_notes_flag: bool, cv_h: str | None) -> list:
    companies = []
    if not data_dir.exists():
        return companies
    for company_dir in sorted(data_dir.iterdir()):
        if not company_dir.is_dir() or company_dir.name.startswith("_"):
            continue
        jobs = []
        for json_file in sorted(company_dir.glob("*.json")):
            if json_file.name.startswith("_"):
                continue
            job = _load_json(json_file)
            job["role_id"]  = json_file.stem
            job["has_pdf"]  = json_file.with_suffix(".pdf").exists()
            job["score"]    = _load_score(data_dir, company_dir.name, json_file.stem,
                                          mode, use_notes_flag, cv_h)
            if "added_at" not in job:
                job["added_at"] = datetime.fromtimestamp(json_file.stat().st_mtime).isoformat()
            jobs.append(job)
        if not jobs:
            continue
        info_path = company_dir / "_company.json"
        info = _load_json(info_path) if info_path.exists() else {}
        # Pre-compute top score for sidebar
        scored = [j["score"]["score"] for j in jobs
                  if not j.get("archived") and j.get("score")]
        companies.append({
            "name": company_dir.name,
            "jobs": jobs,
            "info": info,
            "archived": bool(info.get("archived")),
            "top_score": max(scored) if scored else None,
        })
    return companies


def _get_job(data_dir: Path, company: str, role_id: str, mode: str,
             use_notes_flag: bool, cv_h: str | None) -> dict:
    path = data_dir / company / f"{role_id}.json"
    if not path.exists():
        raise Http404
    job = _load_json(path)
    job["role_id"]   = role_id
    job["has_pdf"]   = path.with_suffix(".pdf").exists()
    if "added_at" not in job:
        job["added_at"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    job["score"]      = _load_score(data_dir, company, role_id, mode, use_notes_flag, cv_h)
    delta = None
    if use_notes_flag and job["score"]:
        plain = _load_score(data_dir, company, role_id, mode, False, cv_h)
        if plain is not None:
            delta = job["score"]["score"] - plain["score"]
    job["score_delta"] = delta
    job["all_scores"]  = _all_cv_scores(data_dir, company, role_id)
    return job


def _save_job(data_dir: Path, company_raw: str, job_data: dict,
              pdf_bytes: bytes | None = None) -> tuple[str, str]:
    company_description = job_data.pop("company_description", None)
    title = job_data.get("title", "Unknown Role")
    company = _slugify_company(company_raw)
    company_dir = data_dir / company
    company_dir.mkdir(parents=True, exist_ok=True)

    role_id = _make_role_id(title)
    if (company_dir / f"{role_id}.json").exists():
        raise ValueError(f'A job titled "{title}" already exists for {company_raw}.')

    job_data.setdefault("added_at", datetime.now().isoformat())
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


def _modal_cv_redirect(request):
    ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    base = ref.split("?")[0]
    return HttpResponseRedirect(base + "?modal=cv")


def _modal_add_jobs_redirect(request):
    ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    base = ref.split("?")[0]
    return HttpResponseRedirect(base + "?modal=add-jobs")


# ------------------------------------------------------------------ #
# Views — settings/mode                                               #
# ------------------------------------------------------------------ #

@private_view
def notes_save(request):
    notes = request.POST.get("notes", "").strip()
    data_dir = _data_dir(request)
    data_dir.mkdir(parents=True, exist_ok=True)
    _notes_path(data_dir).write_text(notes, encoding="utf-8")
    ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    return HttpResponseRedirect(ref)


@private_view
def set_mode(request):
    mode = request.POST.get("mode", "normal")
    request.session["scoring_mode"] = mode if mode in ("normal", "brutal") else "normal"
    ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    return HttpResponseRedirect(ref)


@private_view
def set_notes_mode(request):
    request.session["use_notes"] = request.POST.get("use_notes") == "1"
    ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    return HttpResponseRedirect(ref)


# ------------------------------------------------------------------ #
# Views — browsing                                                    #
# ------------------------------------------------------------------ #

@private_view
def help_page(request):
    return render(request, "jobs/help.html")


@private_view
def index(request):
    data_dir    = _data_dir(request)
    mode        = _current_mode(request)
    use_notes_f = _use_notes(request)
    cv_h        = _cv_hash(data_dir)
    companies   = _get_companies(data_dir, mode, use_notes_f, cv_h)
    active   = [c for c in companies if not c["archived"]]
    archived = [c for c in companies if c["archived"]]
    return render(request, "jobs/index.html", {
        "active_companies": active,
        "archived_companies": archived,
    })


@private_view
def company_view(request, company):
    data_dir = _data_dir(request)
    company_dir = data_dir / company
    if not company_dir.is_dir():
        raise Http404
    mode        = _current_mode(request)
    use_notes_f = _use_notes(request)
    cv_h        = _cv_hash(data_dir)
    info_path = company_dir / "_company.json"
    company_info = _load_json(info_path) if info_path.exists() else {}
    jobs = []
    for json_file in sorted(company_dir.glob("*.json")):
        if json_file.name.startswith("_"):
            continue
        job = _load_json(json_file)
        job["role_id"] = json_file.stem
        job["has_pdf"] = json_file.with_suffix(".pdf").exists()
        job["score"]   = _load_score(data_dir, company, json_file.stem, mode, use_notes_f, cv_h)
        if "added_at" not in job:
            job["added_at"] = datetime.fromtimestamp(json_file.stat().st_mtime).isoformat()
        jobs.append(job)
    jobs.sort(key=lambda j: (j["score"] or {}).get("score", 0), reverse=True)
    active   = [j for j in jobs if not j.get("archived")]
    archived = [j for j in jobs if j.get("archived")]
    return render(request, "jobs/company.html", {
        "company": company,
        "company_info": company_info,
        "active_jobs": active,
        "archived_jobs": archived,
    })


@private_view
def job_view(request, company, role_id):
    data_dir    = _data_dir(request)
    mode        = _current_mode(request)
    use_notes_f = _use_notes(request)
    cv_h        = _cv_hash(data_dir)
    job = _get_job(data_dir, company, role_id, mode, use_notes_f, cv_h)
    return render(request, "jobs/job.html", {"company": company, "job": job})


@private_view
def job_pdf(request, company, role_id):
    data_dir = _data_dir(request)
    path = data_dir / company / f"{role_id}.pdf"
    if not path.exists():
        raise Http404
    return FileResponse(open(path, "rb"), content_type="application/pdf")


# ------------------------------------------------------------------ #
# Views — CV management                                               #
# ------------------------------------------------------------------ #

@private_view
def cv_upload(request):
    f = request.FILES.get("cv")
    if not f or not f.name.lower().endswith(".pdf"):
        messages.warning(request, "Please upload a PDF file.")
        return _modal_cv_redirect(request)
    pdf_bytes = f.read()
    h = hashlib.sha256(pdf_bytes + f.name.encode()).hexdigest()
    data_dir = _data_dir(request)
    _cvs_dir(data_dir).mkdir(parents=True, exist_ok=True)
    idx = _cv_index(data_dir)
    if h in idx.get("cvs", {}):
        messages.warning(request, "This CV has already been uploaded.")
        return _modal_cv_redirect(request)
    (_cvs_dir(data_dir) / f"{h}.pdf").write_bytes(pdf_bytes)
    name = Path(f.name).stem.replace("_", " ").replace("-", " ").strip() or "CV"
    idx.setdefault("cvs", {})[h] = {"name": name, "uploaded": datetime.now().isoformat()}
    idx["selected"] = h
    _save_cv_index(data_dir, idx)
    return _modal_cv_redirect(request)


@private_view
def cv_select(request, cv_hash):
    data_dir = _data_dir(request)
    idx = _cv_index(data_dir)
    if cv_hash in idx.get("cvs", {}) and (_cvs_dir(data_dir) / f"{cv_hash}.pdf").exists():
        idx["selected"] = cv_hash
        _save_cv_index(data_dir, idx)
    return _modal_cv_redirect(request)


@private_view
def cv_rename(request, cv_hash):
    name = request.POST.get("name", "").strip() or "CV"
    data_dir = _data_dir(request)
    idx = _cv_index(data_dir)
    if cv_hash in idx.get("cvs", {}):
        idx["cvs"][cv_hash]["name"] = name
        _save_cv_index(data_dir, idx)
    ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    return HttpResponseRedirect(ref)


@private_view
def cv_delete(request, cv_hash):
    data_dir = _data_dir(request)
    idx = _cv_index(data_dir)
    cvs = idx.get("cvs", {})
    if cv_hash in cvs:
        p = _cvs_dir(data_dir) / f"{cv_hash}.pdf"
        if p.exists():
            p.unlink()
        del cvs[cv_hash]
        if idx.get("selected") == cv_hash:
            idx["selected"] = next(iter(cvs), None)
        _save_cv_index(data_dir, idx)
    return _modal_cv_redirect(request)


@private_view
def cv_view(request):
    data_dir = _data_dir(request)
    p = _selected_cv_path(data_dir)
    if not p:
        raise Http404
    return FileResponse(open(p, "rb"), content_type="application/pdf")


@private_view
def cv_view_specific(request, cv_hash):
    data_dir = _data_dir(request)
    p = _cvs_dir(data_dir) / f"{cv_hash}.pdf"
    if not p.exists():
        raise Http404
    return FileResponse(open(p, "rb"), content_type="application/pdf")


# ------------------------------------------------------------------ #
# Views — Add Jobs                                                    #
# ------------------------------------------------------------------ #

@private_view
def add_job_url(request):
    company_raw = request.POST.get("company", "").strip()
    pdf_file    = request.FILES.get("jd_pdf")
    url         = request.POST.get("jd_url", "").strip()

    if not pdf_file and not url:
        messages.warning(request, "Provide either a PDF/TXT file or a URL.")
        return _modal_add_jobs_redirect(request)

    client = _openai_client()
    if not client:
        messages.warning(request, "OPENAI_KEY is not configured.")
        return _modal_add_jobs_redirect(request)

    pdf_bytes = None
    if pdf_file:
        fname = pdf_file.name.lower()
        if fname.endswith(".pdf"):
            pdf_bytes = pdf_file.read()
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            jd_text = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
        elif fname.endswith(".txt"):
            jd_text = pdf_file.read().decode("utf-8", errors="replace").strip()
        else:
            messages.warning(request, "Please upload a PDF or TXT file.")
            return _modal_add_jobs_redirect(request)
    else:
        try:
            pdf_bytes, jd_text = _url_to_pdf_and_text(url)
        except Exception as e:
            log.warning("Failed to render URL %s: %s", url, e)
            messages.warning(request, "Could not load the URL. Try uploading a PDF or pasting the text instead.")
            return _modal_add_jobs_redirect(request)

    job_data = _analyse_jd(jd_text, client, url=url)
    if not job_data.get("title", "").strip() and not job_data.get("description", "").strip():
        messages.warning(request, "The analysis returned no job content. The URL or file may not contain a job posting.")
        return _modal_add_jobs_redirect(request)
    resolved = company_raw or job_data.get("company", "").strip()
    if not resolved:
        messages.warning(request, "Could not determine the company name. Please fill in the Company field.")
        return _modal_add_jobs_redirect(request)
    job_data["company"] = resolved
    job_data["source"]  = "url" if url else "manual"
    try:
        data_dir = _data_dir(request)
        company, role_id = _save_job(data_dir, resolved, job_data, pdf_bytes)
    except ValueError as e:
        messages.warning(request, str(e))
        return _modal_add_jobs_redirect(request)
    return HttpResponseRedirect(reverse("jobs_job", args=[company, role_id]))


@private_view
def add_job_text(request):
    company_raw = request.POST.get("company", "").strip()
    text        = request.POST.get("text", "").strip()
    url         = request.POST.get("jd_url", "").strip()

    if not text:
        messages.warning(request, "Job description text is required.")
        return _modal_add_jobs_redirect(request)

    client = _openai_client()
    if not client:
        messages.warning(request, "OPENAI_KEY is not configured.")
        return _modal_add_jobs_redirect(request)

    job_data = _analyse_jd(text, client, url=url)
    if not job_data.get("title", "").strip() and not job_data.get("description", "").strip():
        messages.warning(request, "The analysis returned no job content.")
        return _modal_add_jobs_redirect(request)
    resolved = company_raw or job_data.get("company", "").strip()
    if not resolved:
        messages.warning(request, "Could not determine the company name. Please fill in the Company field.")
        return _modal_add_jobs_redirect(request)
    job_data["company"] = resolved
    job_data["source"]  = "text"
    try:
        data_dir = _data_dir(request)
        company, role_id = _save_job(data_dir, resolved, job_data)
    except ValueError as e:
        messages.warning(request, str(e))
        return _modal_add_jobs_redirect(request)
    return HttpResponseRedirect(reverse("jobs_job", args=[company, role_id]))


@private_view
def scrape_categories(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    board   = data.get("board", "lever")
    company = data.get("company", "").strip()
    url     = data.get("url", "").strip()
    data_dir = _data_dir(request)

    if board == "lever":
        try:
            from lever_scraper import LeverScraper
        except ImportError:
            return JsonResponse({"error": "Lever scraper not available."}, status=500)
        if not company:
            return JsonResponse({"error": "Company slug is required."}, status=400)
        base_url = f"https://jobs.lever.co/{company}"
        try:
            jobs = LeverScraper().setup(data_dir).fetch_jobs(base_url)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        try:
            from generic_scraper import GenericScraper
        except ImportError:
            return JsonResponse({"error": "Generic scraper not available."}, status=500)
        html_src = data.get("html_src", "").strip()
        if not url and not html_src:
            return JsonResponse({"error": "Enter the careers page URL or paste HTML source."}, status=400)
        client = _openai_client()
        if not client:
            return JsonResponse({"error": "OPENAI_KEY is required for generic scraping."}, status=400)
        base_url = url or "unknown"
        multi_company = bool(data.get("multi_company", False))
        try:
            jobs = GenericScraper().setup(data_dir, client, multi_company=multi_company).fetch_jobs(
                base_url, html_src=html_src or None)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    for job in jobs:
        job_url = job.get("url", "")
        if job_url:
            role_id = hashlib.sha256(job_url.encode()).hexdigest()
            job["exists"] = any(
                (d / f"{role_id}.json").exists()
                for d in data_dir.iterdir()
                if d.is_dir() and not d.name.startswith("_")
            ) if data_dir.exists() else False
    return JsonResponse({"jobs": jobs, "base_url": base_url})


@private_view
def scrape_confirm(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    import uuid
    limit = data.get("limit")
    jobs  = data.get("jobs") or []
    if limit:
        jobs = jobs[:int(limit)]
    request.session["_scrape_params"] = {
        "board":          data.get("board", "lever"),
        "company":        data.get("company", ""),
        "jobs":           jobs,
        "timeout":        int(data.get("timeout") or 30),
        "openai_timeout": int(data.get("openai_timeout") or 120),
        "multi_company":  bool(data.get("multi_company", False)),
    }
    request.session.modified = True
    return JsonResponse({"ok": True})


@private_view
def scrape_stream(request):
    params = request.session.pop("_scrape_params", None)
    request.session.modified = True
    if not params:
        return HttpResponse("No scrape session", status=400)

    board          = params.get("board", "lever")
    company_raw    = params.get("company", "").strip()
    jobs           = params.get("jobs", [])
    timeout        = params.get("timeout", 30)
    openai_timeout = params.get("openai_timeout", 120)
    multi_company  = params.get("multi_company", False)
    client         = _openai_client()
    data_dir       = _data_dir(request)

    def _slugify(name: str) -> str:
        import unicodedata
        s = unicodedata.normalize("NFKD", name.lower())
        s = s.encode("ascii", "ignore").decode("ascii")
        s = re.sub(r"[^\w\s-]", "", s)
        return re.sub(r"[\s-]+", "_", s).strip("_") or "company"

    def generate():
        total = len(jobs)
        if not total:
            yield f"data: {json.dumps({'done': True, 'total': 0})}\n\n"
            return
        if board == "lever":
            from lever_scraper import LeverScraper
            scraper = LeverScraper().setup(data_dir, client, timeout=timeout, openai_timeout=openai_timeout)
            # Pass company=None so the LLM-extracted name determines the folder slug.
            # Pre-populate each stub with the user-typed slug as fallback (used when OpenAI is off).
            scrape_jobs = [{"company": company_raw, **j} for j in jobs]
            fixed_company = None
            display_name  = None
        else:
            from generic_scraper import GenericScraper
            scraper = GenericScraper().setup(data_dir, client, timeout=timeout,
                                             openai_timeout=openai_timeout, multi_company=multi_company)
            scrape_jobs   = jobs
            fixed_company = _slugify(company_raw) if company_raw else None
            display_name  = company_raw or None
        last_company = fixed_company or company_raw
        for event in scraper.scrape_iter(scrape_jobs, fixed_company, company_name=display_name):
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

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


# ------------------------------------------------------------------ #
# Views — scoring                                                     #
# ------------------------------------------------------------------ #

@private_view
def score_one(request, company, role_id):
    data_dir = _data_dir(request)
    if not _selected_cv_path(data_dir):
        messages.warning(request, "No CV uploaded.")
        ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
        return HttpResponseRedirect(ref)
    client = _openai_client()
    if not client:
        messages.warning(request, "OPENAI_KEY is not configured.")
        ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
        return HttpResponseRedirect(ref)
    mode        = _current_mode(request)
    use_notes_f = _use_notes(request)
    cv_h        = _cv_hash(data_dir)
    job = _get_job(data_dir, company, role_id, mode, use_notes_f, cv_h)
    result = _do_score(data_dir, job, client, mode, use_notes_f)
    _save_score(data_dir, company, role_id, result, mode, use_notes_f)
    ref = request.META.get("HTTP_REFERER", reverse("jobs_job", args=[company, role_id]))
    return HttpResponseRedirect(ref)


@private_view
def score_company_stream(request, company):
    data_dir = _data_dir(request)
    if not _selected_cv_path(data_dir):
        return HttpResponse("No CV uploaded", status=400)
    client = _openai_client()
    if not client:
        return HttpResponse("OPENAI_KEY not set", status=400)
    company_dir = data_dir / company
    if not company_dir.is_dir():
        raise Http404
    mode        = _current_mode(request)
    use_notes_f = _use_notes(request)
    cv_h        = _cv_hash(data_dir)

    to_score = [
        f for f in sorted(company_dir.glob("*.json"))
        if not f.name.startswith("_") and _load_score(data_dir, company, f.stem,
                                                        mode, use_notes_f, cv_h) is None
    ]
    total = len(to_score)

    def generate():
        failed = 0
        for i, json_file in enumerate(to_score, 1):
            job = _load_json(json_file)
            title = job.get("title", "?")
            yield f"data: {json.dumps({'current': i, 'total': total, 'title': title})}\n\n"
            last_error = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    result = _do_score(data_dir, job, client, mode, use_notes_f)
                    _save_score(data_dir, company, json_file.stem, result, mode, use_notes_f)
                    last_error = None
                    break
                except Exception as e:
                    last_error = str(e)
                    if attempt < MAX_RETRIES:
                        yield f"data: {json.dumps({'current': i, 'total': total, 'title': title, 'retry': attempt, 'error': last_error})}\n\n"
            if last_error:
                failed += 1
                yield f"data: {json.dumps({'current': i, 'total': total, 'title': title, 'failed': True, 'error': last_error})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@private_view
def clear_scores(request, company):
    data_dir = _data_dir(request)
    scores_dir = data_dir / company / "_scores"
    if scores_dir.is_dir():
        for f in scores_dir.glob("*.json"):
            f.unlink()
    return HttpResponseRedirect(reverse("jobs_company", args=[company]))


# ------------------------------------------------------------------ #
# Views — archive / delete                                            #
# ------------------------------------------------------------------ #

@private_view
def delete_job(request, company, role_id):
    data_dir = _data_dir(request)
    base = data_dir / company
    for ext in (".json", ".pdf"):
        p = base / f"{role_id}{ext}"
        if p.exists():
            p.unlink()
    scores_dir = base / "_scores"
    if scores_dir.is_dir():
        for f in scores_dir.glob(f"{role_id}_*.json"):
            f.unlink()
    remaining = [f for f in base.glob("*.json") if not f.name.startswith("_")]
    if not remaining:
        shutil.rmtree(base)
        return HttpResponseRedirect(reverse("jobs_index"))
    return HttpResponseRedirect(reverse("jobs_company", args=[company]))


@private_view
def archive_company(request, company):
    data_dir = _data_dir(request)
    _set_archived(data_dir / company / "_company.json", True)
    ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    return HttpResponseRedirect(ref)


@private_view
def unarchive_company(request, company):
    data_dir = _data_dir(request)
    _set_archived(data_dir / company / "_company.json", False)
    ref = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    return HttpResponseRedirect(ref)


@private_view
def archive_job(request, company, role_id):
    data_dir = _data_dir(request)
    _set_archived(data_dir / company / f"{role_id}.json", True)
    return HttpResponseRedirect(reverse("jobs_company", args=[company]))


@private_view
def unarchive_job(request, company, role_id):
    data_dir = _data_dir(request)
    _set_archived(data_dir / company / f"{role_id}.json", False)
    return HttpResponseRedirect(reverse("jobs_company", args=[company]))
