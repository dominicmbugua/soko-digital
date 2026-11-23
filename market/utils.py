import re

from django.conf import settings

from .models import Profile

_PHONE = re.compile(r"^(?:\+?254|0)([17]\d{8})$")


def normalise_phone(raw):
    """'0712 345 678' -> '254712345678'. Returns None if it isn't a Kenyan mobile."""
    m = _PHONE.match(re.sub(r"[\s-]", "", raw or ""))
    return "254" + m.group(1) if m else None


def fee_for(produce_value):
    """Platform fee, rounded half up to whole shillings."""
    return (produce_value * settings.SOKO_FEE_PERCENT + 50) // 100


def role_of(user):
    """'farmer', 'buyer' or None (e.g. an admin with no profile)."""
    if not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    return profile.role if profile else Profile.objects.filter(user=user).values_list("role", flat=True).first()


EMOJI = {"potatoes": "🥔", "maize": "🌽", "tomatoes": "🍅", "kale": "🥬",
         "onions": "🧅", "beans": "🫘", "bananas": "🍌", "avocados": "🥑"}


PHOTO_EXTS = ("webp", "jpg", "jpeg", "png")


def photo_url(slug):
    """URL of static/images/produce/<slug>.(webp|jpg|jpeg|png) if that photo exists, else "" (the UI then
    shows the illustration). Drop real photos into that folder named after the produce slug."""
    from django.contrib.staticfiles import finders
    from django.contrib.staticfiles.storage import staticfiles_storage
    from django.templatetags.static import static

    for ext in PHOTO_EXTS:
        rel = f"images/produce/{slug}.{ext}"
        if finders.find(rel) or staticfiles_storage.exists(rel):
            return static(rel)
    return ""


def emoji_for(slug):
    return EMOJI.get(slug, "🌱")
