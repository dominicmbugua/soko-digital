"""Payment gateway. For now it is SIMULATED: no real money moves.

When we integrate Safaricom Daraja (M-Pesa STK Push), only this file changes:
collect_payment() will start the STK push and the callback view will confirm it.
"""
import secrets


def collect_payment(order):
    """Pretend the buyer approved the M-Pesa prompt. Returns (ok, receipt)."""
    return True, "SIM" + secrets.token_hex(4).upper()
