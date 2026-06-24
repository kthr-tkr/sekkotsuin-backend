import re

from django import template

from apps.staff.utils import get_staff_display_name


register = template.Library()
HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


@register.filter
def staff_display_name(value):
    return get_staff_display_name(value)


@register.filter
def safe_theme_color(value, fallback="#2563EB"):
    """Return only a CSS-safe full hex color for staff theme variables."""
    candidate = str(value or "").strip()
    safe_fallback = str(fallback or "#2563EB").strip()
    if not HEX_COLOR_PATTERN.fullmatch(safe_fallback):
        safe_fallback = "#2563EB"
    return candidate if HEX_COLOR_PATTERN.fullmatch(candidate) else safe_fallback
