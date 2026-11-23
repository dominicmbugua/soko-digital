"""Session-based shopping cart: {listing_id: kilograms}. Works before login; checkout needs a buyer account."""
from django.conf import settings

from .models import Listing
from .utils import emoji_for, photo_url

KEY = "cart"


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.data = dict(self.session.get(KEY, {}))

    def _save(self):
        self.session[KEY] = self.data
        self.session.modified = True

    def get(self, listing_id):
        return self.data.get(str(listing_id), 0)

    def set(self, listing_id, qty):
        if qty <= 0:
            self.data.pop(str(listing_id), None)
        else:
            self.data[str(listing_id)] = qty
        self._save()

    def clear(self):
        self.data = {}
        self._save()

    def lines(self):
        """Current lines with live prices. Quietly fixes stale items and returns notes about what changed."""
        listings = {l.id: l for l in Listing.objects.filter(pk__in=[int(k) for k in self.data], is_active=True)
                    .select_related("produce", "farmer")}
        out, notes, changed = [], [], False
        for key, qty in list(self.data.items()):
            l = listings.get(int(key))
            if not l or l.qty_kg < 1:
                self.data.pop(key)
                notes.append("An item in your cart sold out or was removed, so we took it out.")
                changed = True
                continue
            if qty > l.qty_kg:
                qty = self.data[key] = l.qty_kg
                notes.append(f"Only {qty} kg of {l.produce.name} is left, so we adjusted your quantity.")
                changed = True
            out.append({
                "id": l.id, "produce": l.produce.slug, "name": l.produce.name, "emoji": emoji_for(l.produce.slug), "photo": photo_url(l.produce.slug),
                "farmer": l.farmer_name, "location": l.location, "grade": l.grade, "price": l.price_per_kg,
                "qty": qty, "max": l.qty_kg, "line": l.price_per_kg * qty, "delivery": settings.SOKO_DELIVERY_PER_KG * qty,
            })
        if changed:
            self._save()
        return out, notes

    def summary(self):
        lines, notes = self.lines()
        subtotal = sum(x["line"] for x in lines)
        delivery = sum(x["delivery"] for x in lines)
        return {"items": lines, "count": len(lines), "kg": sum(x["qty"] for x in lines), "subtotal": subtotal,
                "delivery": delivery, "total": subtotal + delivery, "notes": notes,
                "deliveryPerKg": settings.SOKO_DELIVERY_PER_KG}
