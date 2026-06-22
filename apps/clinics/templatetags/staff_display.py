from django import template

from apps.staff.utils import get_staff_display_name


register = template.Library()


@register.filter
def staff_display_name(value):
    return get_staff_display_name(value)
