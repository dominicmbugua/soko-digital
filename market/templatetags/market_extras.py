from django import template
from django.utils.html import format_html

from market.utils import emoji_for, photo_url

register = template.Library()

KNOWN_ART = {"potatoes", "maize", "tomatoes", "kale", "onions", "beans", "bananas", "avocados"}


@register.filter
def emoji(slug):
    """Kept for backwards compatibility. The UI now uses produce_art / icon instead."""
    return emoji_for(slug)


@register.simple_tag
def produce_art(slug, size=""):
    """Real photo if static/images/produce/<slug>.jpg exists, otherwise the illustration from templates/partials/sprite.html.
    `size` is an optional CSS class (xs, sm, md, lg)."""
    url = photo_url(slug)
    if url:   # a real photo is available for this produce
        return format_html('<img class="pa photo {}" src="{}" alt="" loading="lazy" decoding="async">', size, url)
    sym = slug if slug in KNOWN_ART else "_default"
    return format_html('<svg class="pa {}" aria-hidden="true" focusable="false"><use href="#p-{}"/></svg>', size, sym)


@register.simple_tag
def icon(name, size=""):
    """Line icon from the sprite (Lucide). Example: {% icon "truck" %}"""
    return format_html('<svg class="i {}" aria-hidden="true" focusable="false"><use href="#i-{}"/></svg>', size, name)
