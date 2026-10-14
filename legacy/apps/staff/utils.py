import re

from django.contrib.auth import get_user_model


def get_staff_display_name(user_or_staff):
    """Return the staff-facing name while keeping login IDs secondary."""
    if user_or_staff is None:
        return "担当者未設定"

    user = getattr(user_or_staff, "user", None) or user_or_staff
    full_name = " ".join(
        part.strip()
        for part in (
            str(getattr(user, "last_name", "") or ""),
            str(getattr(user, "first_name", "") or ""),
        )
        if part.strip()
    )
    if full_name:
        return full_name

    profile = getattr(user, "profile", None)
    profile_display_name = str(
        getattr(profile, "display_name", "") or ""
    ).strip()
    if profile_display_name:
        return profile_display_name

    email = str(getattr(user, "email", "") or "").strip()
    if email:
        return email

    return str(getattr(user, "username", "") or "担当者未設定")


def build_unique_staff_username(*, email="", last_name="", first_name=""):
    """Generate an internal username only when a new staff account is made."""
    user_model = get_user_model()
    source = str(email or "").strip().lower()
    if not source:
        source = f"{last_name or ''}{first_name or ''}".strip() or "staff"
    base = re.sub(r"[^\w.@+-]+", "-", source, flags=re.UNICODE).strip("-._")
    base = (base or "staff")[:140]

    candidate = base
    suffix = 1
    while user_model.objects.filter(username=candidate).exists():
        suffix += 1
        tail = f"-{suffix}"
        candidate = f"{base[:150 - len(tail)]}{tail}"
    return candidate
