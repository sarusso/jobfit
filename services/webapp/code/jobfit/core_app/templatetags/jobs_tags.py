from datetime import datetime

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def score_badge(score_obj, size=""):
    """Render a coloured score badge. Accepts a Score model instance, a dict, or None."""
    if not score_obj:
        return mark_safe(f'<span class="badge score-none {size}">&nbsp;&nbsp;&mdash;&nbsp;&nbsp;</span>')
    if isinstance(score_obj, dict):
        s = score_obj.get("score")
        reasoning = score_obj.get("reasoning", "").replace('"', "&quot;")
    else:
        s = getattr(score_obj, "score", None)
        reasoning = getattr(score_obj, "reasoning", "").replace('"', "&quot;")
    if s is None:
        return mark_safe(f'<span class="badge score-none {size}">&nbsp;&nbsp;&mdash;&nbsp;&nbsp;</span>')
    cls = "score-high" if s >= 9 else ("score-mid" if s >= 7 else "score-low")
    return mark_safe(f'<span class="badge {cls} {size}" title="{reasoning}">{s}/10</span>')


@register.filter
def datefmt(value):
    """Format a datetime object or ISO string to '1 Jan 2025'."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return value[:10]
    try:
        return value.strftime("%-d %b %Y")
    except Exception:
        return str(value)[:10]
