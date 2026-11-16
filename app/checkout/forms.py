"""Checkout form options, validation and totals.

Preview only: no order is stored, no payment is taken and stock isn't reserved.
"""

import re
from decimal import Decimal

from app.cart.store import FREE_SHIPPING_THRESHOLD

# Phnom Penh first (most orders), then the provinces alphabetically.
PROVINCES = [
    "Phnom Penh", "Banteay Meanchey", "Battambang", "Kampong Cham", "Kampong Chhnang",
    "Kampong Speu", "Kampong Thom", "Kampot", "Kandal", "Kep", "Koh Kong", "Kratie",
    "Mondulkiri", "Oddar Meanchey", "Pailin", "Preah Sihanouk", "Preah Vihear", "Prey Veng",
    "Pursat", "Ratanakiri", "Siem Reap", "Stung Treng", "Svay Rieng", "Takeo", "Tbong Khmum",
]

DELIVERY_FEE = Decimal("3")
PICKUP_LOCATION = "Keyora Showroom, Phnom Penh"
DELIVERY_METHODS = {
    "delivery": {"label": "Delivery", "body": "To your address in 1-3 business days"},
    "pickup": {"label": "Pickup", "body": f"{PICKUP_LOCATION} · ready in 1 business day"},
}
PAYMENT_METHODS = {"khqr": "KHQR"}

FIELDS = ("email", "phone", "receiver_name", "province", "address", "delivery", "note", "payment")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Cambodian numbers: 0 or +855, then 8–9 digits (e.g. 012 345 678, +855 97 123 4567).
_PHONE = re.compile(r"^(?:\+855|0)\d{8,9}$")


def clean_phone(raw):
    """Strip spaces, dashes, dots and brackets: "012 345-678" -> "012345678"."""
    return re.sub(r"[\s\-().]", "", raw or "")


def valid_email(email):
    return bool(_EMAIL.match(email))


def valid_phone(phone):
    """`phone` must already be cleaned."""
    return bool(_PHONE.match(phone))


def format_phone(phone):
    """012345678 -> 012 345 678; +85597123456 -> +855 97 123 456."""
    if phone.startswith("+855"):
        rest = phone[4:]
        return f"+855 {rest[:2]} {rest[2:5]} {rest[5:]}"
    return f"{phone[:3]} {phone[3:6]} {phone[6:]}"


def shipping_fee(method, subtotal):
    if method == "pickup" or subtotal >= FREE_SHIPPING_THRESHOLD:
        return Decimal(0)
    return DELIVERY_FEE


def validate(form):
    """(cleaned data, {field: message}). Address fields are only required for delivery."""
    data = {name: (form.get(name) or "").strip() for name in FIELDS}
    data["phone"] = clean_phone(data["phone"])
    errors = {}

    if not valid_email(data["email"]):
        errors["email"] = "Enter a valid email address."
    if not valid_phone(data["phone"]):
        errors["phone"] = "Enter a Cambodian phone number, e.g. 012 345 678."

    if data["delivery"] not in DELIVERY_METHODS:
        errors["delivery"] = "Choose delivery or pickup."
    if data["delivery"] == "pickup":
        data.update(province="", address="")
    if not data["receiver_name"]:
        errors["receiver_name"] = "Enter the receiver's name."
    elif len(data["receiver_name"]) > 80:
        errors["receiver_name"] = "Keep the name under 80 characters."
    if data["delivery"] == "delivery":
        if data["province"] not in PROVINCES:
            errors["province"] = "Choose a province or city."
        if not data["address"]:
            errors["address"] = "Enter the address details."
        elif len(data["address"]) > 300:
            errors["address"] = "Keep the address under 300 characters."

    if len(data["note"]) > 500:
        errors["note"] = "Keep the note under 500 characters."
    if data["payment"] not in PAYMENT_METHODS:
        errors["payment"] = "Choose a payment method."
    return data, errors
