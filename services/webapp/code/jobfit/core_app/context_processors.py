import json
import hashlib
from pathlib import Path
from datetime import datetime

from django.conf import settings


def _data_dir(user):
    return Path(settings.DATA_DIR) / user.username


def _cvs_dir(data_dir):
    return data_dir / "_cvs"


def _cv_index(data_dir):
    idx_path = _cvs_dir(data_dir) / "_index.json"
    if not idx_path.exists():
        return {"selected": None, "cvs": {}}
    with open(idx_path, encoding="utf-8") as f:
        return json.load(f)


def _selected_cv_path(data_dir):
    idx = _cv_index(data_dir)
    h = idx.get("selected")
    if not h:
        return None
    p = _cvs_dir(data_dir) / f"{h}.pdf"
    return p if p.exists() else None


def _all_cvs(data_dir):
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


def _company_names(data_dir):
    if not data_dir.exists():
        return []
    return sorted(
        d.name for d in data_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )


def jobs_context(request):
    if not request.user.is_authenticated:
        return {}
    data_dir = _data_dir(request.user)
    cv_path = _selected_cv_path(data_dir)
    notes_path = data_dir / "_notes.txt"
    candidate_notes = ""
    if notes_path.exists():
        try:
            candidate_notes = notes_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    has_openai_key = bool(settings.OPENAI_KEY)
    return {
        "cv_uploaded": cv_path is not None,
        "all_cvs": _all_cvs(data_dir),
        "has_openai_key": has_openai_key,
        "can_score": cv_path is not None and has_openai_key,
        "scoring_mode": request.session.get("scoring_mode", "normal"),
        "use_notes": request.session.get("use_notes", False),
        "existing_companies": _company_names(data_dir),
        "candidate_notes": candidate_notes,
    }
