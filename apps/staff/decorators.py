from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def _is_staff_user(user):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    valid_roles = {"admin", "reception", "practitioner"}
    return getattr(user, "role", None) in valid_roles


def staff_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("/staff/login/")

        if _is_staff_user(request.user):
            return view_func(request, *args, **kwargs)

        messages.error(request, "権限がありません。")
        return redirect("/")

    return _wrapped