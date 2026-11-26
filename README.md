# Soko Digital (Django)

Marketplace connecting Kenyan farmers with business buyers. Payment is held until delivery is confirmed.
Payments are **simulated** until you add your Safaricom keys (see *Going live with M-Pesa* below), then they use real M-Pesa STK Push.

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

## Pages
| Page | URL | Notes |
|---|---|---|
| Home | `/` | Hero, a few fresh listings, who it is for, how it works, the route |
| Marketplace | `/market/` | All listings with produce filter (`/market/?produce=maize`) |
| Sell produce | `/sell/` | How selling works + the listing form (farmers only) |
| How it works | `/how-it-works/` | Buyer and farmer guides, money example (uses the real fee and delivery rate), order tracker |
| About | `/about/` | Why Soko Digital exists, what it does, how it earns |
| FAQ | `/faq/` | Buyers, farmers, delivery. Quotes the configured fee and delivery rate |
| Contact | `/contact/` | Form saves to **Admin > Contact messages** (tick "handled" once replied). Has a hidden spam trap |
| Terms, Privacy | `/terms/`, `/privacy/` | Short plain-language pilot versions. **Have a lawyer review before launch** |
| 404 | any unknown URL | Friendly page, shown when `DEBUG=False` |

Page templates are in `templates/pages/`; the shared header/footer are in `templates/partials/`. Fee and delivery numbers on every page come from `SOKO_FEE_PERCENT` / `SOKO_DELIVERY_PER_KG` in `config/settings.py`, so change them once.

**Set your contact details** (shown in the footer and on the Contact page; any you leave blank are hidden):
```
set SOKO_CONTACT_EMAIL=hello@yourdomain.com        (Windows;  macOS/Linux: export ...)
set SOKO_CONTACT_PHONE=+254 7XX XXX XXX
set SOKO_WHATSAPP=2547XXXXXXXX
```
or type them straight into `config/settings.py`. Run `python manage.py migrate` after updating (adds the contact-messages table).

## Buyer journey: cart to checkout
1. **Browse and add to cart** (works before login). Pick kilograms on a listing card, then **Add to cart**. The cart lives in the session and survives login.
2. **Cart drawer** (basket icon in the navbar): change kilograms, remove items, see produce + delivery (KES 6/kg) + total.
3. **Checkout** (`/checkout/`, buyers only): delivery address, notes and M-Pesa number. Guests are sent to log in or register and come back here.
4. **Pay**: one M-Pesa payment for the whole cart (a PIN prompt on the buyer's phone; see below). Stock is locked and checked first, so nothing is oversold and no half-orders are created.
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
| M-Pesa (STK Push, callback, status check; simulated until keys are set) | `market/payments.py`, `market/cart_api.py` |
| Front-end talking to the API | `static/js/main.js` |
| Demo data | `market/management/commands/seed_demo.py` |
| Tests (`python manage.py test`) | `market/tests.py` |

## Going live with M-Pesa (STK Push)
**What the buyer sees:** at the last step they confirm the number to pay with, press *Pay*, and get an M-Pesa PIN prompt on that phone. The page shows "Check your phone" and waits. When the buyer enters the PIN, the orders become *Payment held* and they land on the confirmation page with the M-Pesa receipt. If they cancel, enter a wrong PIN or it times out, they see why and can try again (or pay with another number). A buyer can also finish later from *Buyer dashboard > Pay now*.

**Where the money is received:** on the Paybill or Till you set in `MPESA_SHORTCODE` (and `MPESA_PARTY_B` for a Till). It is shown to the buyer at checkout and on the pay prompt, and every attempt is saved as a **Payment** (phone, amount, receipt, which Paybill/Till, how it ended). Ops sees them in `/dashboard/ops/` (*Received via M-Pesa* and the *M-Pesa payments* table) and in **Admin > Payments**.

**Set up (sandbox first):**
1. Create an app at developer.safaricom.co.ke and copy its Consumer Key and Secret, the test shortcode and passkey.
2. Start a tunnel so Safaricom can reach you: `ngrok http 8000`. Then uncomment the ngrok lines at the bottom of the settings `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` and use your own ngrok host.
3. Set the variables (Windows `set NAME=value`, macOS/Linux `export NAME=value`) and restart the server:
```
MPESA_ENV=sandbox
MPESA_CONSUMER_KEY=...
MPESA_CONSUMER_SECRET=...
MPESA_SHORTCODE=...                  # the Paybill (or Till store number) that receives the money
MPESA_PASSKEY=...
MPESA_CALLBACK_BASE_URL=https://your-name.ngrok-free.app
MPESA_CALLBACK_TOKEN=<a long random string>      # e.g. python -c "import secrets; print(secrets.token_urlsafe(32))"
# Till instead of Paybill:  MPESA_TRANSACTION_TYPE=CustomerBuyGoodsOnline  and  MPESA_PARTY_B=<till number>
```
4. `python manage.py migrate` (adds the Payment table), then check out. If any required variable is missing, the site stays in simulated mode (the footer and checkout say so).
5. For production use `MPESA_ENV=production` with your real shortcode, passkey and keys, `DEBUG=False`, and an https domain.

**How it stays safe:**
- The browser never says what was paid. Safaricom tells our server on `/api/mpesa/callback/<MPESA_CALLBACK_TOKEN>/`; the secret in the URL keeps strangers out, and a callback is matched to a payment by Safaricom's own request id.
- Orders are only released if the amount matches. A wrong amount, a double payment, or money arriving for orders ops already cancelled is marked **Needs review** and is *not* released; refund those from M-Pesa by hand.
- If the callback is late or lost, the status poll asks Safaricom directly. If the buyer never answers, it gives up after 2 minutes (`MPESA_PROMPT_TIMEOUT`), but money that arrives later is still recorded.
- Only one prompt is open per checkout at a time, so a double-click cannot charge twice.

**Check before launch:** run a real KES 1 test on production and confirm the Payment row, the receipt and the money in your Paybill/Till. The sandbox does not move real money.

## Paying farmers (manual payouts)
When a buyer confirms delivery (or ops releases a disputed order), the order is *Settled* and the farmer is **owed** their price minus our fee. Nothing is sent automatically. In `/dashboard/ops/`, **Pay farmers** lists each farmer with the phone to send to and the exact amount.
1. Send that amount to that number from your M-Pesa (Send Money).
2. Paste the M-Pesa code of your transfer and press **Mark paid**.

That records who was paid, when, and the code, and the farmer sees "Sent" with the code on their dashboard. If an order settles while the page is open, only the orders you actually paid are recorded; the new one stays on the list. The same orders can never be marked paid twice.

## Unpaid orders expire
A checkout that is not paid within `SOKO_UNPAID_EXPIRY_MINUTES` (30, in `config/settings.py`) is cancelled and the produce goes back on sale. It never cancels a checkout with a PIN prompt still open, or one where money arrived and is waiting for review. A buyer who opens an expired checkout is told it is closed and can order again.

Expiry also runs by itself when people use the site (at most once a minute). For a tidy, reliable setup run it on a schedule: `python manage.py expire_unpaid` every 5 minutes (Windows Task Scheduler, or cron on a server).

## Order flow (enforced on the server)
`AWAITING_PAYMENT` -> `PAYMENT_HELD` -> `DELIVERED` -> `SETTLED` (farmer paid price minus 8%) or `DISPUTED`.
Steps can't be skipped or repeated. Stock is locked while an order is created so it can't be oversold.

## Known gaps / next steps
1. Real M-Pesa is built; it needs your Daraja keys and a public callback URL (see *Going live with M-Pesa*).
2. Farmer payouts are **manual** for now (see *Paying farmers*). Automatic payouts (M-Pesa B2C) need a Safaricom-approved business account and are not built.
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
