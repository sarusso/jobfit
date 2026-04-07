from datetime import datetime

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def score_badge(score_obj, size=""):
    if not score_obj:
        return mark_safe(f'<span class="badge score-none {size}">&nbsp;&nbsp;&mdash;&nbsp;&nbsp;</span>')
    s = score_obj.get("score") if isinstance(score_obj, dict) else getattr(score_obj, "score", None)
    if s is None:
        return mark_safe(f'<span class="badge score-none {size}">&nbsp;&nbsp;&mdash;&nbsp;&nbsp;</span>')
    cls = "score-high" if s >= 9 else ("score-mid" if s >= 5 else "score-low")
    reasoning = (score_obj.get("reasoning", "") if isinstance(score_obj, dict) else "").replace('"', "&quot;")
    return mark_safe(f'<span class="badge {cls} {size}" title="{reasoning}">{s}/10</span>')


@register.filter
def datefmt(iso):
    try:
        return datetime.fromisoformat(str(iso)).strftime("%-d %b %Y")
    except Exception:
        return str(iso)[:10] if iso else ""
