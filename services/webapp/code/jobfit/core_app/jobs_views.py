"""
jobs_views.py — Django views for the jobs app, backed by Django models.

File storage layout (per user):
    DATA_DIR/<username>/
        _cvs/<hash>.pdf          # CV files
        jobs/<uuid>.pdf          # job source PDFs
        jobs/<uuid>.txt          # job source text (future)
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import uuid as uuid_module
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import (FileResponse, Http404, HttpResponse,
                         HttpResponseRedirect, JsonResponse,
                         StreamingHttpResponse)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .decorators import private_view
from .models import CV, Company, Job, Notes, Score

log = logging.getLogger(__name__)

SCORE_TIMEOUT = 60
MAX_RETRIES   = 3


# ------------------------------------------------------------------ #
# Path helpers (files only — metadata lives in models)               #
# ------------------------------------------------------------------ #

def _data_dir(request) -> Path:
    return Path(settings.DATA_DIR) / request.user.username

def _cvs_dir(data_dir: Path) -> Path:
    return data_dir / "_cvs"

def _jobs_dir(data_dir: Path) -> Path:
    return data_dir / "jobs"


# ------------------------------------------------------------------ #
# Session helpers                                                     #
# ------------------------------------------------------------------ #

def _current_mode(request) -> str:
    return request.session.get("scoring_mode", "normal")

def _use_notes(request) -> bool:
    return request.session.get("use_notes", False)

def _get_selected_cv(request):
    """Return the selected CV model instance, or None."""
    cv_id = request.session.get("selected_cv_id")
    if not cv_id:
        return None
    try:
        return CV.objects.get(id=cv_id, user=request.user)
    except CV.DoesNotExist:
        return None

def _get_notes_text(request) -> str:
    try:
        return Notes.objects.get(user=request.user).content.strip()
    except Notes.DoesNotExist:
        return ""


# ------------------------------------------------------------------ #
# Company / slug helpers                                              #
# ------------------------------------------------------------------ #

def _slugify_company(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", name.lower())
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"[\s-]+", "_", s).strip("_") or "unknown"

def _get_or_create_company(user, name_raw: str, description: str = "") -> Company:
    slug = _slugify_company(name_raw)
    company, created = Company.objects.get_or_create(
        user=user,
        slug=slug,
        defaults={"name": name_raw, "description": description},
    )
    return company


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


def _do_score(user, job: Job, cv: CV, client, mode: str = "normal",
              with_notes_text: str = "") -> dict:
    """Call OpenAI to score a job against a CV. Returns the raw result dict."""
    data_dir = Path(settings.DATA_DIR) / user.username
    cv_file  = data_dir / cv.file_path
    cv_b64   = base64.standard_b64encode(cv_file.read_bytes()).decode()

    notes_section = (
        f"Additional context provided by the candidate (treat as authoritative):\n{with_notes_text}\n\n"
        if with_notes_text else ""
    )
    job_dict = {
        "title":            job.title,
        "company":          job.company.name or job.company.slug,
        "location":         job.location,
        "employment_type":  job.employment_type,
        "experience_level": job.experience_level,
        "summary":          job.summary,
        "description":      job.description,
        "responsibilities": job.responsibilities,
        "requirements":     job.requirements,
        "nice_to_have":     job.nice_to_have,
        "salary":           job.salary,
    }
    prompt = (_PROMPT_NORMAL if mode == "normal" else _PROMPT_BRUTAL) + notes_section + (
        "Job description (JSON):\n"
        + json.dumps(job_dict, indent=2, ensure_ascii=False)
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
    return json.loads(response.choices[0].message.content)


def _save_score(job: Job, cv: CV, mode: str, result: dict,
                with_notes_text: str = "") -> Score:
    score, _ = Score.objects.update_or_create(
        job=job, cv=cv, mode=mode,
        defaults={
            "score":      result["score"],
            "reasoning":  result.get("reasoning", ""),
            "strengths":  result.get("strengths", []),
            "gaps":       result.get("gaps", []),
            "with_notes": with_notes_text or None,
        },
    )
    return score


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
# Job creation helper                                                 #
# ------------------------------------------------------------------ #

def _create_job(user, job_data: dict, pdf_bytes: bytes | None = None,
                source_override: str = "") -> Job:
    """Create Company + Job from analysed job_data dict. Saves PDF if provided."""
    company_raw = job_data.get("company", "").strip() or "Unknown"
    description = job_data.pop("company_description", "") or ""

    company = _get_or_create_company(user, company_raw, description)

    source = source_override or job_data.get("source", "text")

    job = Job.objects.create(
        company          = company,
        title            = job_data.get("title", ""),
        location         = job_data.get("location", "") or "",
        employment_type  = job_data.get("employment_type", "") or "",
        experience_level = job_data.get("experience_level", "") or "",
        summary          = job_data.get("summary", "") or "",
        description      = job_data.get("description", "") or "",
        responsibilities = job_data.get("responsibilities") or [],
        requirements     = job_data.get("requirements") or [],
        nice_to_have     = job_data.get("nice_to_have") or [],
        salary           = str(job_data.get("salary") or ""),
        source           = source,
    )

    if pdf_bytes:
        data_dir = Path(settings.DATA_DIR) / user.username
        jobs_dir = _jobs_dir(data_dir)
        jobs_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = jobs_dir / f"{job.id}.pdf"
        pdf_path.write_bytes(pdf_bytes)
        job.source_file_path = f"jobs/{job.id}.pdf"
        job.save(update_fields=["source_file_path"])

    return job


# ------------------------------------------------------------------ #
# Redirect helpers                                                    #
# ------------------------------------------------------------------ #

def _modal_cv_redirect(request):
    ref  = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    base = ref.split("?")[0]
    return HttpResponseRedirect(base + "?modal=cv")

def _modal_add_jobs_redirect(request):
    ref  = request.META.get("HTTP_REFERER", reverse("jobs_index"))
    base = ref.split("?")[0]
    return HttpResponseRedirect(base + "?modal=add-jobs")


# ------------------------------------------------------------------ #
# Views — settings / mode                                            #
# ------------------------------------------------------------------ #

@private_view
def notes_save(request):
    content = request.POST.get("notes", "").strip()
    Notes.objects.update_or_create(user=request.user, defaults={"content": content})
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("jobs_index")))


@private_view
def set_mode(request):
    mode = request.POST.get("mode", "normal")
    request.session["scoring_mode"] = mode if mode in ("normal", "brutal") else "normal"
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("jobs_index")))


@private_view
def set_notes_mode(request):
    request.session["use_notes"] = request.POST.get("use_notes") == "1"
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("jobs_index")))


# ------------------------------------------------------------------ #
# Views — browsing                                                    #
# ------------------------------------------------------------------ #

@private_view
def help_page(request):
    return render(request, "jobs/help.html")


@private_view
def index(request):
    mode           = _current_mode(request)
    selected_cv    = _get_selected_cv(request)
    companies      = list(
        Company.objects.filter(user=request.user)
        .prefetch_related('jobs__scores')
        .order_by('slug')
    )

    for company in companies:
        jobs   = company.jobs.all()
        scored = []
        for job in jobs:
            if not job.archived and selected_cv:
                s = job.scores.filter(cv=selected_cv, mode=mode).first()
                if s:
                    scored.append(s.score)
        company.top_score = max(scored) if scored else None

    active   = [c for c in companies if not c.archived]
    archived = [c for c in companies if c.archived]
    return render(request, "jobs/index.html", {
        "active_companies":   active,
        "archived_companies": archived,
    })


@private_view
def company_view(request, company_slug):
    company     = get_object_or_404(Company, user=request.user, slug=company_slug)
    mode        = _current_mode(request)
    selected_cv = _get_selected_cv(request)

    jobs = list(company.jobs.prefetch_related('scores').order_by('-added_at'))
    for job in jobs:
        job.score   = job.scores.filter(cv=selected_cv, mode=mode).first() if selected_cv else None
        job.has_pdf = bool(job.source_file_path)

    active   = [j for j in jobs if not j.archived]
    archived = [j for j in jobs if j.archived]
    return render(request, "jobs/company.html", {
        "company":      company,
        "active_jobs":  active,
        "archived_jobs": archived,
    })


@private_view
def job_view(request, company_slug, job_id):
    company     = get_object_or_404(Company, user=request.user, slug=company_slug)
    job         = get_object_or_404(Job, company=company, id=job_id)
    mode        = _current_mode(request)
    selected_cv = _get_selected_cv(request)

    job.score   = job.scores.filter(cv=selected_cv, mode=mode).first() if selected_cv else None
    job.has_pdf = bool(job.source_file_path)
    job.all_scores = list(job.scores.select_related('cv').order_by('cv__name', 'mode'))

    return render(request, "jobs/job.html", {"company": company, "job": job})


@private_view
def job_pdf(request, company_slug, job_id):
    company = get_object_or_404(Company, user=request.user, slug=company_slug)
    job     = get_object_or_404(Job, company=company, id=job_id)
    if not job.source_file_path:
        raise Http404
    data_dir = _data_dir(request)
    p = data_dir / job.source_file_path
    if not p.exists():
        raise Http404
    return FileResponse(open(p, "rb"), content_type="application/pdf")


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

    if CV.objects.filter(user=request.user, hash=h).exists():
        messages.warning(request, "This CV has already been uploaded.")
        return _modal_cv_redirect(request)

    data_dir = _data_dir(request)
    _cvs_dir(data_dir).mkdir(parents=True, exist_ok=True)
    file_path = f"_cvs/{h}.pdf"
    (data_dir / file_path).write_bytes(pdf_bytes)

    name = Path(f.name).stem.replace("_", " ").replace("-", " ").strip() or "CV"
    cv = CV.objects.create(user=request.user, hash=h, name=name, file_path=file_path)
    request.session["selected_cv_id"] = str(cv.id)
    return _modal_cv_redirect(request)


@private_view
def cv_select(request, cv_id):
    cv = get_object_or_404(CV, id=cv_id, user=request.user)
    request.session["selected_cv_id"] = str(cv.id)
    return _modal_cv_redirect(request)


@private_view
def cv_rename(request, cv_id):
    name = request.POST.get("name", "").strip() or "CV"
    CV.objects.filter(id=cv_id, user=request.user).update(name=name)
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("jobs_index")))


@private_view
def cv_delete(request, cv_id):
    cv = get_object_or_404(CV, id=cv_id, user=request.user)
    data_dir = _data_dir(request)
    p = data_dir / cv.file_path
    if p.exists():
        p.unlink()
    if request.session.get("selected_cv_id") == str(cv.id):
        next_cv = CV.objects.filter(user=request.user).exclude(id=cv.id).first()
        request.session["selected_cv_id"] = str(next_cv.id) if next_cv else None
    cv.delete()
    return _modal_cv_redirect(request)


@private_view
def cv_view(request):
    cv = _get_selected_cv(request)
    if not cv:
        raise Http404
    data_dir = _data_dir(request)
    p = data_dir / cv.file_path
    if not p.exists():
        raise Http404
    return FileResponse(open(p, "rb"), content_type="application/pdf")


@private_view
def cv_view_specific(request, cv_id):
    cv = get_object_or_404(CV, id=cv_id, user=request.user)
    data_dir = _data_dir(request)
    p = data_dir / cv.file_path
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
            reader  = PdfReader(io.BytesIO(pdf_bytes))
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
        messages.warning(request, "The analysis returned no job content.")
        return _modal_add_jobs_redirect(request)

    if company_raw:
        job_data["company"] = company_raw

    if not job_data.get("company", "").strip():
        messages.warning(request, "Could not determine the company name. Please fill in the Company field.")
        return _modal_add_jobs_redirect(request)

    source = url if url else "file"
    job = _create_job(request.user, job_data, pdf_bytes=pdf_bytes, source_override=source)
    return HttpResponseRedirect(reverse("jobs_job", args=[job.company.slug, str(job.id)]))


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

    if company_raw:
        job_data["company"] = company_raw

    if not job_data.get("company", "").strip():
        messages.warning(request, "Could not determine the company name. Please fill in the Company field.")
        return _modal_add_jobs_redirect(request)

    job = _create_job(request.user, job_data, source_override="text")
    return HttpResponseRedirect(reverse("jobs_job", args=[job.company.slug, str(job.id)]))


# ------------------------------------------------------------------ #
# Views — Scraping                                                    #
# ------------------------------------------------------------------ #

@private_view
def scrape_categories(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    board    = data.get("board", "lever")
    company  = data.get("company", "").strip()
    url      = data.get("url", "").strip()

    if board == "lever":
        try:
            from lever_scraper import LeverScraper
        except ImportError:
            return JsonResponse({"error": "Lever scraper not available."}, status=500)
        if not company:
            return JsonResponse({"error": "Company slug is required."}, status=400)
        base_url = f"https://jobs.lever.co/{company}"
        try:
            jobs = LeverScraper().setup(Path(settings.DATA_DIR)).fetch_jobs(base_url)
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
            jobs = GenericScraper().setup(Path(settings.DATA_DIR), client,
                                          multi_company=multi_company).fetch_jobs(
                base_url, html_src=html_src or None)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    # Mark jobs already in the DB
    for job in jobs:
        job_url = job.get("url", "")
        if job_url:
            job["exists"] = Job.objects.filter(
                company__user=request.user, source=job_url
            ).exists()
    return JsonResponse({"jobs": jobs, "base_url": base_url})


@private_view
def scrape_confirm(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
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
    user           = request.user

    # Pre-generate UUIDs and PDF output paths for each job
    jobs_dir = _jobs_dir(data_dir)

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
            scraper = LeverScraper().setup(data_dir, client, timeout=timeout,
                                           openai_timeout=openai_timeout)
            scrape_jobs = []
            for j in jobs:
                job_uuid = str(uuid_module.uuid4())
                scrape_jobs.append({
                    "company":         company_raw,
                    "uuid":            job_uuid,
                    "pdf_output_path": str(jobs_dir / f"{job_uuid}.pdf"),
                    **j,
                })
            fixed_company = None
            display_name  = None
        else:
            from generic_scraper import GenericScraper
            scraper = GenericScraper().setup(data_dir, client, timeout=timeout,
                                             openai_timeout=openai_timeout,
                                             multi_company=multi_company)
            scrape_jobs = []
            for j in jobs:
                job_uuid = str(uuid_module.uuid4())
                scrape_jobs.append({
                    "uuid":            job_uuid,
                    "pdf_output_path": str(jobs_dir / f"{job_uuid}.pdf"),
                    **j,
                })
            fixed_company = _slugify(company_raw) if company_raw else None
            display_name  = company_raw or None

        last_company_slug = fixed_company or _slugify(company_raw) if company_raw else None

        for event in scraper.scrape_iter(scrape_jobs, fixed_company, company_name=display_name):
            event["total"] = total

            # Create Company + Job models from completed events
            if not event.get("starting") and not event.get("error"):
                job_data  = event.get("job_data") or {}
                job_uuid  = event.get("uuid")
                if job_data and job_uuid:
                    jobs_dir.mkdir(parents=True, exist_ok=True)
                    extracted_company = job_data.get("company", "").strip()
                    fallback          = company_raw if board == "lever" else ""
                    company_name_raw  = extracted_company or fallback or "Unknown"
                    description       = job_data.pop("company_description", "") or ""

                    company_obj = _get_or_create_company(user, company_name_raw, description)
                    last_company_slug = company_obj.slug
                    event["company"]  = company_obj.slug

                    pdf_path = jobs_dir / f"{job_uuid}.pdf"
                    try:
                        Job.objects.get_or_create(
                            id=job_uuid,
                            defaults={
                                "company":          company_obj,
                                "title":            job_data.get("title", ""),
                                "location":         job_data.get("location", "") or "",
                                "employment_type":  job_data.get("employment_type", "") or "",
                                "experience_level": job_data.get("experience_level", "") or "",
                                "summary":          job_data.get("summary", "") or "",
                                "description":      job_data.get("description", "") or "",
                                "responsibilities": job_data.get("responsibilities") or [],
                                "requirements":     job_data.get("requirements") or [],
                                "nice_to_have":     job_data.get("nice_to_have") or [],
                                "salary":           str(job_data.get("salary") or ""),
                                "source":           event.get("url", ""),
                                "source_file_path": f"jobs/{job_uuid}.pdf" if pdf_path.exists() else "",
                            },
                        )
                    except Exception as e:
                        log.error("Failed to create Job model for %s: %s", job_uuid, e)

            yield f"data: {json.dumps(event)}\n\n"

        done_payload: dict = {"done": True, "total": total}
        if last_company_slug:
            done_payload["company"] = last_company_slug
        yield f"data: {json.dumps(done_payload)}\n\n"

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


# ------------------------------------------------------------------ #
# Views — scoring                                                     #
# ------------------------------------------------------------------ #

@private_view
def score_one(request, company_slug, job_id):
    company     = get_object_or_404(Company, user=request.user, slug=company_slug)
    job         = get_object_or_404(Job, company=company, id=job_id)
    selected_cv = _get_selected_cv(request)
    if not selected_cv:
        messages.warning(request, "No CV selected.")
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("jobs_index")))
    client = _openai_client()
    if not client:
        messages.warning(request, "OPENAI_KEY is not configured.")
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("jobs_index")))

    mode           = _current_mode(request)
    with_notes_txt = _get_notes_text(request) if _use_notes(request) else ""

    result = _do_score(request.user, job, selected_cv, client, mode, with_notes_txt)
    _save_score(job, selected_cv, mode, result, with_notes_txt)

    return HttpResponseRedirect(request.META.get(
        "HTTP_REFERER", reverse("jobs_job", args=[company_slug, str(job.id)])
    ))


@private_view
def score_company_stream(request, company_slug):
    company     = get_object_or_404(Company, user=request.user, slug=company_slug)
    selected_cv = _get_selected_cv(request)
    if not selected_cv:
        return HttpResponse("No CV selected", status=400)
    client = _openai_client()
    if not client:
        return HttpResponse("OPENAI_KEY not set", status=400)

    mode           = _current_mode(request)
    with_notes_txt = _get_notes_text(request) if _use_notes(request) else ""
    user           = request.user

    scored_ids = Score.objects.filter(
        job__company=company, cv=selected_cv, mode=mode
    ).values_list("job_id", flat=True)

    to_score = list(
        company.jobs.filter(archived=False).exclude(id__in=scored_ids).order_by("added_at")
    )
    total = len(to_score)

    def generate():
        for i, job in enumerate(to_score, 1):
            yield f"data: {json.dumps({'current': i, 'total': total, 'title': job.title})}\n\n"
            last_error = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    result = _do_score(user, job, selected_cv, client, mode, with_notes_txt)
                    _save_score(job, selected_cv, mode, result, with_notes_txt)
                    last_error = None
                    break
                except Exception as e:
                    last_error = str(e)
                    if attempt < MAX_RETRIES:
                        yield f"data: {json.dumps({'current': i, 'total': total, 'title': job.title, 'retry': attempt, 'error': last_error})}\n\n"
            if last_error:
                yield f"data: {json.dumps({'current': i, 'total': total, 'title': job.title, 'failed': True, 'error': last_error})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@private_view
def clear_scores(request, company_slug):
    company = get_object_or_404(Company, user=request.user, slug=company_slug)
    Score.objects.filter(job__company=company).delete()
    return HttpResponseRedirect(reverse("jobs_company", args=[company_slug]))


# ------------------------------------------------------------------ #
# Views — archive / delete                                           #
# ------------------------------------------------------------------ #

@private_view
def delete_job(request, company_slug, job_id):
    company = get_object_or_404(Company, user=request.user, slug=company_slug)
    job     = get_object_or_404(Job, company=company, id=job_id)

    if job.source_file_path:
        data_dir = _data_dir(request)
        p = data_dir / job.source_file_path
        if p.exists():
            p.unlink()

    job.delete()

    if not company.jobs.exists():
        company.delete()
        return HttpResponseRedirect(reverse("jobs_index"))
    return HttpResponseRedirect(reverse("jobs_company", args=[company_slug]))


@private_view
def archive_company(request, company_slug):
    company = get_object_or_404(Company, user=request.user, slug=company_slug)
    company.archived = True
    company.save(update_fields=["archived"])
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("jobs_index")))


@private_view
def unarchive_company(request, company_slug):
    company = get_object_or_404(Company, user=request.user, slug=company_slug)
    company.archived = False
    company.save(update_fields=["archived"])
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("jobs_index")))


@private_view
def archive_job(request, company_slug, job_id):
    company = get_object_or_404(Company, user=request.user, slug=company_slug)
    job     = get_object_or_404(Job, company=company, id=job_id)
    job.archived = True
    job.save(update_fields=["archived"])
    return HttpResponseRedirect(reverse("jobs_company", args=[company_slug]))


@private_view
def unarchive_job(request, company_slug, job_id):
    company = get_object_or_404(Company, user=request.user, slug=company_slug)
    job     = get_object_or_404(Job, company=company, id=job_id)
    job.archived = False
    job.save(update_fields=["archived"])
    return HttpResponseRedirect(reverse("jobs_company", args=[company_slug]))
