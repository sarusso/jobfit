from django.conf import settings

from .models import CV, Notes, Company


def jobs_context(request):
    if not request.user.is_authenticated:
        return {}

    selected_cv_id = request.session.get('selected_cv_id')
    selected_cv = None
    if selected_cv_id:
        try:
            selected_cv = CV.objects.get(id=selected_cv_id, user=request.user)
        except CV.DoesNotExist:
            pass

    all_cvs = []
    for cv in CV.objects.filter(user=request.user).order_by('-uploaded_at'):
        all_cvs.append({
            "id":       str(cv.id),
            "name":     cv.name,
            "uploaded": cv.uploaded_at.strftime("%-d %B %Y, %H:%M") if cv.uploaded_at else "",
            "selected": selected_cv is not None and cv.id == selected_cv.id,
        })

    try:
        candidate_notes = Notes.objects.get(user=request.user).content
    except Notes.DoesNotExist:
        candidate_notes = ""

    has_openai_key = bool(settings.OPENAI_KEY)

    existing_companies = list(
        Company.objects.filter(user=request.user, archived=False)
        .values_list('slug', flat=True)
        .order_by('slug')
    )

    return {
        "cv_uploaded":        selected_cv is not None,
        "all_cvs":            all_cvs,
        "has_openai_key":     has_openai_key,
        "can_score":          selected_cv is not None and has_openai_key,
        "scoring_mode":       request.session.get("scoring_mode", "normal"),
        "use_notes":          request.session.get("use_notes", False),
        "existing_companies": existing_companies,
        "candidate_notes":    candidate_notes,
    }
