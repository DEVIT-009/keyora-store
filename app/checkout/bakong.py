"""Bakong Open API client (https://api-bakong.nbc.gov.kh/v1). Server-side only.

Bakong has no webhooks: we learn about a payment only by asking with the QR's md5, and we
only ask when the customer clicks "I've paid" (app/checkout/orders.py `confirm`).
`responseCode == 0` with `data` means paid. Anything we can't read (timeout, 401 token,
403 non-Cambodian IP, 429, 5xx) raises BakongUnavailable — that is never "unpaid".
Logs carry the status, codes and md5, never the token.
"""

import logging

import requests
from flask import current_app

log = logging.getLogger(__name__)


class BakongUnavailable(Exception):
    """Bakong couldn't be asked or didn't give a usable answer; try again later."""


def _post(path, payload):
    config = current_app.config
    if not config["BAKONG_TOKEN"]:
        raise BakongUnavailable("BAKONG_TOKEN is not set")
    try:
        response = requests.post(
            config["BAKONG_API_URL"].rstrip("/") + path,
            json=payload,
            headers={"Authorization": f"Bearer {config['BAKONG_TOKEN']}"},
            timeout=config["BAKONG_TIMEOUT"],
        )
    except requests.RequestException as exc:
        log.warning("Bakong %s failed: %s", path, type(exc).__name__)
        raise BakongUnavailable(type(exc).__name__) from exc
    if not response.ok:
        # 401 = bad/expired token, 403 = not a Cambodian IP, 429 = rate limited, 5xx = busy.
        log.warning("Bakong %s returned HTTP %s", path, response.status_code)
        raise BakongUnavailable(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise BakongUnavailable("invalid JSON") from exc


def check_md5(md5):
    """Transaction `data` dict if paid, else None."""
    body = _post("/check_transaction_by_md5", {"md5": md5})
    if body.get("responseCode") == 0 and body.get("data"):
        return body["data"]
    # errorCode 1 = not found (not paid yet), 3 = failed; both mean "not paid".
    log.debug("Bakong md5 %s not paid (errorCode %s)", md5, body.get("errorCode"))
    return None


def check_account(account_id):
    """True if the Bakong account exists. errorCode 11 = not found, 12 = bad format."""
    body = _post("/check_bakong_account", {"accountId": account_id})
    return body.get("responseCode") == 0
