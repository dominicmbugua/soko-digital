from django import template

from market.utils import emoji_for

register = template.Library()


@register.filter
def emoji(slug):
    return emoji_for(slug)
