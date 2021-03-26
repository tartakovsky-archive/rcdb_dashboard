import math

from django import template

register = template.Library()


@register.filter(name='truncate')
def truncate(value, arg):
    if not value or not arg:
        return value
    return math.floor(float(value) * 10 ** arg) / 10 ** arg


@register.filter(name='to_int')
def to_int(value):
    if value:
        return int(value)
    return value
