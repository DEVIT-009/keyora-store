"""Bakong KHQR: builds the EMVCo string a banking app scans, its md5, and the QR image.

The string is byte-for-byte what `bakong-khqr`'s `KHQR.create_qr()` produces (same amount
formatting, phone normalisation and tag-62 sub-field order), except that the expiry in
tag 99 is our order's `expires_at` — the library only allows whole days. The image is the
library's official KHQR card (`KHQR.qr_image`), so the pay page doesn't draw its own.

A KHQR is `tag(2) + length(2) + value` fields ending in a CRC-16 (`6304XXXX`). The md5 of
the exact string is the id we later ask Bakong about, so the string is stored on the order
and never rebuilt (it contains the creation time).
"""

import hashlib
from decimal import Decimal

from bakong_khqr import KHQR

CURRENCY_CODES = {"USD": "840", "KHR": "116"}
MERCHANT_CATEGORY = "5999"  # misc. retail

# Max lengths from the KHQR spec. Values are validated, never truncated.
LIMITS = {
    "account_id": 32, "merchant_name": 25, "merchant_city": 15,
    "amount": 13, "bill_number": 25, "mobile_number": 25, "store_label": 25, "terminal_label": 25,
}


class KHQRError(ValueError):
    pass


def tlv(tag, value):
    if len(value) > 99:
        raise KHQRError(f"KHQR tag {tag} too long")
    return f"{tag}{len(value):02d}{value}"


def crc16(payload):
    """CRC-16/CCITT-FALSE over the UTF-8 bytes, as 4 uppercase hex digits."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def format_amount(amount, currency):
    """Like bakong-khqr: 2 decimals without trailing zeros ("129", "12.5", "0.01"); KHR whole riel."""
    amount = Decimal(amount)
    if currency == "KHR":
        return str(int(amount))
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def normalize_phone(phone):
    """Like bakong-khqr: digits only, local 0-prefixed form ("+855 96 723 4500" -> "0967234500")."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("855"):
        digits = digits[3:]
    return digits if digits.startswith("0") else "0" + digits


def _check(fields):
    for name, value in fields.items():
        if value is None:
            continue
        if len(value) > LIMITS[name]:
            raise KHQRError(f"{name} exceeds {LIMITS[name]} characters")
        # Name/city/labels must be ASCII: some banking apps count bytes, which breaks length + CRC.
        if not value.isascii():
            raise KHQRError(f"{name} must be ASCII")


def _additional_data(bill_number, mobile_number=None, store_label=None, terminal_label=None):
    """Tag 62 in bakong-khqr's sub-field order: store (03), phone (02), bill (01), terminal (07)."""
    return (
        (tlv("03", store_label) if store_label else "")
        + (tlv("02", mobile_number) if mobile_number else "")
        + (tlv("01", bill_number) if bill_number else "")
        + (tlv("07", terminal_label) if terminal_label else "")
    )


def _payload(template_tag, account_info, currency, amount, merchant_name, merchant_city,
             additional, created_ms, expires_ms):
    p = (
        tlv("00", "01")
        + tlv("01", "12")  # dynamic: one amount, one payment
        + tlv(template_tag, account_info)
        + tlv("52", MERCHANT_CATEGORY)
        + tlv("53", CURRENCY_CODES[currency])
        + tlv("54", amount)
        + tlv("58", "KH")
        + tlv("59", merchant_name)
        + tlv("60", merchant_city)
        + (tlv("62", additional) if additional else "")
        + tlv("99", tlv("00", str(created_ms)) + tlv("01", str(expires_ms)))
        + "6304"
    )
    return p + crc16(p)


def build(account_id, merchant_name, merchant_city, currency, amount, bill_number,
          created_at, expires_at, mobile_number=None, store_label=None, terminal_label=None):
    """(qr_string, md5) for a dynamic individual KHQR. Times are aware datetimes."""
    if currency not in CURRENCY_CODES:
        raise KHQRError(f"Unsupported currency {currency}")
    amount_str = format_amount(amount, currency)
    minimum = Decimal("0.01") if currency == "USD" else Decimal(100)
    if Decimal(amount_str) < minimum:
        raise KHQRError(f"Amount below the {currency} minimum")
    if mobile_number:
        mobile_number = normalize_phone(mobile_number)
    _check({
        "account_id": account_id, "merchant_name": merchant_name, "merchant_city": merchant_city,
        "amount": amount_str, "bill_number": bill_number, "mobile_number": mobile_number,
        "store_label": store_label, "terminal_label": terminal_label,
    })
    if "@" not in account_id:
        raise KHQRError("account_id must look like name@bank")

    created_ms, expires_ms = int(created_at.timestamp() * 1000), int(expires_at.timestamp() * 1000)
    if expires_ms <= created_ms:
        raise KHQRError("expires_at must be after created_at")

    additional = _additional_data(bill_number, mobile_number, store_label, terminal_label)
    qr = _payload("29", tlv("00", account_id), currency, amount_str, merchant_name, merchant_city,
                  additional, created_ms, expires_ms)
    return qr, md5(qr)


def md5(qr):
    return hashlib.md5(qr.encode("utf-8")).hexdigest()


def image_data_uri(qr):
    """The official KHQR card (red header, merchant, amount, QR) as a PNG data: URI.

    Rendered locally by bakong-khqr; no token or network call is involved.
    """
    return KHQR().qr_image(qr, format="base64_uri")


def selftest():
    """Rebuild the official SDK sample (merchant QR, tag 30); its CRC must be 58D8."""
    additional = tlv("01", "Invoice#069") + tlv("03", "Coffee Khlaing") + tlv("07", "Cooooooooooooooooooounter 2")
    qr = _payload("30", tlv("00", "john_smith@devb"), "USD", "500.0", "John Smith", "Phnom Penh",
                  additional, 1727340564907, 1727340624907)
    return qr[-4:] == "58D8"
