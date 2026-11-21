# Soko Digital (Django)

Marketplace connecting Kenyan farmers with business buyers. Payment is held until delivery is confirmed.
Payments are **simulated** for now (no real M-Pesa yet).

## Run it
```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate       # creates/updates db.sqlite3 and loads the 8 produce types
python manage.py seed_demo     # optional: demo farmers, listings and a buyer
python manage.py createsuperuser   # your own admin login
python manage.py runserver
```
Open http://127.0.0.1:8000/ and the admin at http://127.0.0.1:8000/admin/

Demo logins (after `seed_demo`), password `soko12345` for all:
farmers `wanjiku`, `peter`, `grace`, `samuel`, `faith`, `john`, `mary`, `david`; buyer `buyer1`.

## See the database (db.sqlite3)
- **Admin site:** `/admin/` shows Profiles, Produce, Listings and Orders.
- **VS Code:** install the "SQLite Viewer" extension, then click `db.sqlite3`.
- **DB Browser for SQLite** (sqlitebrowser.org): File > Open Database > Browse Data.
- **Terminal:** `python manage.py dbshell`, then `.tables` and `SELECT * FROM market_listing;`

Tables: `auth_user` (accounts), `market_profile` (farmer/buyer role, phone), `market_produce`,
`market_listing`, `market_order`.

## Buyer journey: cart to checkout
1. **Browse and add to cart** (works before login). Pick kilograms on a listing card, then **Add to cart**. The cart lives in the session and survives login.
2. **Cart drawer** (basket icon in the navbar): change kilograms, remove items, see produce + delivery (KES 6/kg) + total.
3. **Checkout** (`/checkout/`, buyers only): delivery address, notes and M-Pesa number. Guests are sent to log in or register and come back here.
4. **Pay**: one simulated M-Pesa payment for the whole cart. Stock is locked and checked first, so nothing is oversold and no half-orders are created.
5. **Confirmation** (`/checkout/<id>/done/`): receipt, order list, what happens next. If payment failed, a "Pay now" button retries it.
A checkout creates one order per listing (so each farmer is tracked and paid separately). Ops sees the delivery address in the queue.
Code: `market/cart.py`, `market/cart_api.py`, `static/js/cart.js`, `static/js/checkout.js`, `templates/shop/`.

## Dashboards
| Who | URL | What they do |
|---|---|---|
| Farmer | `/dashboard/farmer/` | Earnings chart, listings (edit / pause / delete), incoming orders |
| Buyer | `/dashboard/buyer/` | Order tracker, pay, confirm delivery, report a problem, order again |
| Ops (staff) | `/dashboard/ops/` | Delivery queue, disputes (pay farmer or refund buyer), cancel unpaid, sales and fee totals |

`/dashboard/` sends each person to the right one. Ops needs `is_staff` (superusers have it).
After `seed_demo`: log in as `wanjiku` (farmer), `buyer1` (buyer) or `ops1` (staff), password `soko12345`.
Order statuses now also include `REFUNDED` and `CANCELLED`; both return the stock to the listing.

## How it fits together
| Piece | File |
|---|---|
| Models (the tables) | `market/models.py` |
| Register / login | `market/views.py`, `market/forms.py`, `templates/registration/` |
| Dashboards | `market/dashboards.py`, `market/services.py`, `templates/dashboard/`, `static/js/dashboard.js` |
| JSON API (all price, fee and status logic) | `market/api.py` |
| Payment gateway (simulated; swap for Daraja later) | `market/payments.py` |
| Front-end talking to the API | `static/js/main.js` |
| Demo data | `market/management/commands/seed_demo.py` |
| Tests (`python manage.py test`) | `market/tests.py` |

## Order flow (enforced on the server)
`AWAITING_PAYMENT` -> `PAYMENT_HELD` -> `DELIVERED` -> `SETTLED` (farmer paid price minus 8%) or `DISPUTED`.
Steps can't be skipped or repeated. Stock is locked while an order is created so it can't be oversold.

## Known gaps / next steps
1. Real M-Pesa: implement STK Push + callback URL in `payments.py` (Daraja sandbox). The callback needs a public URL (ngrok).
2. Unpaid orders keep stock reserved until ops cancels them. Add an automatic expiry later.
3. Delivery: with `DEMO_MODE = True` the website marks orders delivered. For real use set it to `False`; the delivery team uses the admin action "Mark selected orders as delivered".
4. Real escrow/payout (B2C to the farmer) needs a holding-account arrangement. Out of scope for the demo.
5. Deploy: `DEBUG=False`, `ALLOWED_HOSTS`, secret key from env, Postgres, gunicorn + whitenoise.

## Look and feel
- **Real photos are included** for all 8 produce types in `static/images/produce/` (900x675 JPG). Check the licence/attribution terms of wherever they came from before launch.
- **Replacing or adding photos:** drop photos named after the produce into `static/images/produce/` (`potatoes.jpg`, `maize.jpg`, `tomatoes.jpg`, `kale.jpg`, `onions.jpg`, `beans.jpg`, `bananas.jpg`, `avocados.jpg`), or run `python tools/prep_photos.py <your photos folder>` to resize and crop them. The site uses a photo automatically wherever one exists, and keeps the illustration for any produce without one.
- **No emoji in the UI.** Produce is drawn as illustrations in `templates/partials/sprite.html` (one SVG per produce, id `p-<slug>`), and UI icons are Lucide line icons (ISC licence) in the same file (id `i-<name>`).
- In templates: `{% load market_extras %}` then `{% produce_art p.slug "md" %}` (sizes `xs sm md lg`) or `{% icon "truck" %}`. In JS: `<svg class="pa"><use href="#p-maize"/></svg>`.
- **Adding a new produce type:** it shows a neutral sprout until you add a symbol `p-<slug>` to the sprite and its slug to `KNOWN_ART` in `market/templatetags/market_extras.py`. Add a tint for it in `static/css/style.css` (the `[data-p=...]` rules).
- Design tokens (colours, radii, fonts) are at the top of `static/css/style.css`. Fonts: Bricolage Grotesque (headings) and Figtree (text).
- Scrolling is native. The pinned "journey" scene, parallax, tilting cards and ticker strip were removed on purpose.
- **Entrance animations (WOW.js style, no library):** add `class="wow fadeInUp"` (also `fadeInLeft`, `fadeInRight`, `fadeIn`, `zoomIn`) and optionally `data-wow-delay="0.3s"` to any element. It animates once when it scrolls into view. Code: `static/js/motion.js` and the "Entrance animations" block at the end of `static/css/style.css`. For content added by JavaScript, call `Wow.refresh()` after inserting it (the listings do this).
- `motion.js` also runs the first-visit loading screen (once per browser tab) and the back-to-top button. Everything is skipped for people who set "reduce motion" on their device.
- The `emoji` fields in the API and `utils.emoji_for` are still there for compatibility but the UI no longer uses them.
