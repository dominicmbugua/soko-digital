"""M-Pesa payments (Safaricom Daraja STK Push).

Two modes, chosen by settings.MPESA_SIMULATE:
  * simulated (the default until the keys are set): the payment "succeeds" instantly, no money moves.
  * real: we ask Safaricom to show an M-Pesa PIN prompt on the buyer's phone (STK Push). The result
    arrives later on our callback URL (cart_api.mpesa_callback). While the buyer is deciding, the
    browser polls /api/checkout/<id>/status/, which also asks Safaricom directly if the callback is late.

Every attempt is a `Payment` row. It records the phone that was charged, the Paybill/Till that
received the money (`paid_to`) and the M-Pesa receipt, so ops can always see where money landed.
"""
import base64
import logging
import secrets
import time

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Checkout, Order, Payment

log = logging.getLogger(__name__)
P = Payment.Status

BASES = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}

# What we tell the buyer for the result codes Safaricom sends most often.
FRIENDLY = {
    1: "Your M-Pesa balance is too low for this payment.",
    1001: "Another M-Pesa request is already open on this phone. Wait a minute, then try again.",
    1032: "You cancelled the payment prompt.",
    1037: "The prompt timed out before a PIN was entered.",
    2001: "The M-Pesa PIN was wrong.",
}


class PaymentError(Exception):
    """A problem we can show to the buyer as is."""


# ---------- Which mode, and where the money goes ----------
def simulated():
    return settings.MPESA_SIMULATE


def receiving_account():
    """Human label of the account that receives the money, e.g. 'Paybill 174379' or 'Till 5123456'."""
    if simulated():
        return "Soko Digital (demo)"
    kind = "Till" if settings.MPESA_TRANSACTION_TYPE == "CustomerBuyGoodsOnline" else "Paybill"
    return f"{kind} {settings.MPESA_PARTY_B}"


def collect_payment(obj):
    """Old one-shot payment used by /api/payments/collect/. Returns (ok, receipt).
    Real money can't be taken in one step (the buyer must enter a PIN), so it only works in simulation."""
    if not simulated():
        return False, ""
    return True, "SIM" + secrets.token_hex(4).upper()


# ---------- Talking to Daraja ----------
_token = {"value": "", "expires": 0.0}


def _base():
    return BASES.get(settings.MPESA_ENV, BASES["sandbox"])


def _access_token(force=False):
    if not force and _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    try:
        r = requests.get(_base() + "/oauth/v1/generate", params={"grant_type": "client_credentials"},
                         auth=(settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET), timeout=15)
        r.raise_for_status()
        data = r.json()
        token = data["access_token"]
    except (requests.RequestException, ValueError, KeyError):
        log.exception("Could not get a Daraja access token")
        raise PaymentError("We couldn't reach M-Pesa. Please try again in a moment.")
    _token["value"] = token
    _token["expires"] = time.time() + max(60, int(data.get("expires_in", 3599)) - 60)
    return token


def _post(path, payload):
    """POST to Daraja. Returns (http_status, json_dict). Retries once if the token was refused."""
    for attempt in (1, 2):
        try:
            r = requests.post(_base() + path, json=payload, timeout=20,
                              headers={"Authorization": f"Bearer {_access_token(force=attempt == 2)}"})
        except requests.RequestException:
            log.exception("Daraja request failed: %s", path)
            raise PaymentError("We couldn't reach M-Pesa. Please try again in a moment.")
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 401 and attempt == 1:
            continue
        return r.status_code, data


def _stamp_and_password():
    stamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    raw = f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{stamp}"
    return stamp, base64.b64encode(raw.encode()).decode()


def callback_url():
    return f"{settings.MPESA_CALLBACK_BASE_URL}/api/mpesa/callback/{settings.MPESA_CALLBACK_TOKEN}/"


def send_stk_push(payment):
    """Ask Safaricom to show the PIN prompt on payment.phone. Stores Safaricom's request ids on the payment."""
    stamp, password = _stamp_and_password()
    status, data = _post("/mpesa/stkpush/v1/processrequest", {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": stamp,
        "TransactionType": settings.MPESA_TRANSACTION_TYPE,
        "Amount": payment.amount,
        "PartyA": payment.phone,
        "PartyB": settings.MPESA_PARTY_B,
        "PhoneNumber": payment.phone,
        "CallBackURL": callback_url(),
        "AccountReference": payment.checkout.ref,       # Daraja allows 12 characters
        "TransactionDesc": "Soko order",                # and 13 here
    })
    if status != 200 or str(data.get("ResponseCode")) != "0":
        log.warning("STK push refused (%s): %s", status, data)
        raise PaymentError("M-Pesa couldn't send the prompt to that number. Check the number and try again.")
    payment.merchant_request_id = data.get("MerchantRequestID", "")
    payment.checkout_request_id = data.get("CheckoutRequestID", "")
    payment.save(update_fields=["merchant_request_id", "checkout_request_id", "updated"])


def query_stk(payment):
    """Ask Safaricom how a push ended. Returns (result_code, description), or (None, '') while it is still open."""
    stamp, password = _stamp_and_password()
    status, data = _post("/mpesa/stkpushquery/v1/query", {
        "BusinessShortCode": settings.MPESA_SHORTCODE, "Password": password, "Timestamp": stamp,
        "CheckoutRequestID": payment.checkout_request_id})
    try:
        return int(data["ResultCode"]), data.get("ResultDesc", "")
    except (KeyError, TypeError, ValueError):
        return None, ""                                  # Daraja answers with an error while the prompt is open


# ---------- Recording the result ----------
@transaction.atomic
def finish_payment(payment_id, *, result_code, desc="", receipt="", amount=None, raw=None):
    """Apply the outcome of a payment. Safe to call twice (callback retries, poll racing the callback).

    result_code 0 = the money arrived. Any other number = it failed. None = we stopped waiting (timeout).
    """
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    checkout = Checkout.objects.select_for_update().get(pk=payment.checkout_id)
    if raw is not None:
        payment.raw_callback = raw

    if payment.status == P.SUCCESS:
        if receipt and not payment.receipt:              # the status query confirmed it; the callback brings the receipt
            payment.receipt = receipt
            payment.save(update_fields=["receipt", "raw_callback", "updated"])
            Checkout.objects.filter(pk=checkout.pk).update(mpesa_receipt=receipt)
            checkout.orders.filter(mpesa_receipt="").update(mpesa_receipt=receipt)
        return payment
    if payment.status not in (P.PENDING, P.TIMEOUT):     # already failed, cancelled or under review: nothing to change
        return payment

    if result_code is None:                              # we gave up waiting; a late success can still arrive
        payment.status, payment.result_desc = P.TIMEOUT, desc[:255]
        payment.save()
        return payment

    payment.result_code, payment.result_desc = result_code, desc[:255]
    if result_code != 0:
        payment.status = {1032: P.CANCELLED, 1037: P.TIMEOUT}.get(result_code, P.FAILED)
        payment.save()
        return payment

    # The money arrived. Only release the orders if everything lines up; otherwise flag it for a human.
    orders = list(checkout.orders.select_for_update().filter(status=Order.Status.AWAITING_PAYMENT))
    problem = ""
    if amount is not None and int(round(float(amount))) != payment.amount:
        problem = f"Paid KES {amount}, expected KES {payment.amount}."
    elif checkout.is_paid:
        problem = "This checkout was already paid, so this looks like a double payment."
    elif not orders:
        problem = "The orders were cancelled before the money arrived."
    if problem:
        log.error("Payment %s needs review: %s", payment.pk, problem)
        payment.status, payment.result_desc = P.NEEDS_REVIEW, problem
        payment.receipt = receipt or payment.receipt
        payment.save()
        return payment

    for o in orders:
        o.status, o.mpesa_receipt = Order.Status.PAYMENT_HELD, receipt
        o.save()
    checkout.mpesa_receipt, checkout.paid_at = receipt, timezone.now()
    checkout.save()
    payment.status, payment.receipt = P.SUCCESS, receipt
    payment.save()
    return payment


def parse_callback(body):
    """Pull what we need out of Safaricom's callback JSON. Returns None if it isn't an STK callback."""
    try:
        cb = body["Body"]["stkCallback"]
        items = (cb.get("CallbackMetadata") or {}).get("Item") or []
        meta = {i["Name"]: i.get("Value") for i in items if isinstance(i, dict) and "Name" in i}
        return {"checkout_request_id": str(cb["CheckoutRequestID"]), "result_code": int(cb["ResultCode"]),
                "desc": str(cb.get("ResultDesc", "")), "receipt": str(meta.get("MpesaReceiptNumber") or ""),
                "amount": meta.get("Amount")}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def handle_callback(body):
    """Process a callback from Safaricom. Returns True if it matched one of our payments."""
    cb = parse_callback(body)
    if not cb or not cb["checkout_request_id"]:
        log.warning("Ignored an M-Pesa callback we couldn't read: %s", body)
        return False
    payment = Payment.objects.filter(checkout_request_id=cb["checkout_request_id"]).first()
    if not payment:
        log.warning("M-Pesa callback for an unknown payment: %s", cb["checkout_request_id"])
        return False
    finish_payment(payment.pk, result_code=cb["result_code"], desc=cb["desc"], receipt=cb["receipt"],
                   amount=cb["amount"], raw=body)
    return True


def refresh_pending(payment):
    """Called each time the browser polls. The callback is the normal way we learn the result; this covers a
    callback that is late or lost by asking Safaricom directly, and gives up after MPESA_PROMPT_TIMEOUT."""
    if payment.status != P.PENDING or payment.simulated:
        return payment
    now = timezone.now()
    age = (now - payment.created).total_seconds()
    due = not payment.last_query_at or (now - payment.last_query_at).total_seconds() >= 8
    if age >= 20 and due and payment.checkout_request_id:
        Payment.objects.filter(pk=payment.pk).update(last_query_at=now)
        try:
            code, desc = query_stk(payment)
        except PaymentError:
            code = None
        if code is not None:
            finish_payment(payment.pk, result_code=code, desc=desc)
            payment.refresh_from_db()
            return payment
    if age > settings.MPESA_PROMPT_TIMEOUT:
        finish_payment(payment.pk, result_code=None, desc="No answer from the buyer's phone.")
        payment.refresh_from_db()
    return payment


def message_for(payment):
    """One plain sentence for the buyer about where this payment stands."""
    if payment.status == P.SUCCESS:
        return "Payment received."
    if payment.status == P.PENDING:
        return "Check your phone and enter your M-Pesa PIN."
    if payment.status == P.NEEDS_REVIEW:
        return "We received your payment but need to check it. Please don't pay again; our team will contact you."
    if payment.result_code in FRIENDLY:
        return FRIENDLY[payment.result_code]
    if payment.status == P.TIMEOUT:
        return FRIENDLY[1037]
    return "The payment didn't go through. You can try again."
