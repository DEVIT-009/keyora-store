"""Account form validation. Each validate_* returns (cleaned data, {field: message})."""

from app.checkout.forms import PROVINCES, clean_phone, valid_email, valid_phone

PASSWORD_MIN = 8
PASSWORD_MAX = 128


def _strip(form, *names):
    return {name: (form.get(name) or "").strip() for name in names}


def _check_name(data, errors, field="full_name", label="your name"):
    if not data[field]:
        errors[field] = f"Enter {label}."
    elif len(data[field]) > 80:
        errors[field] = "Keep the name under 80 characters."


def _check_new_password(password, errors, field):
    if len(password) < PASSWORD_MIN:
        errors[field] = f"Use at least {PASSWORD_MIN} characters."
    elif len(password) > PASSWORD_MAX:
        errors[field] = f"Use at most {PASSWORD_MAX} characters."


def validate_register(form):
    data = _strip(form, "email", "full_name")
    data["email"] = data["email"].lower()
    data["password"] = form.get("password") or ""  # never stripped: spaces are allowed
    errors = {}
    if not valid_email(data["email"]):
        errors["email"] = "Enter a valid email address."
    _check_name(data, errors)
    _check_new_password(data["password"], errors, "password")
    return data, errors


def validate_login(form):
    data = _strip(form, "email")
    data["password"] = form.get("password") or ""
    data["remember"] = form.get("remember") == "on"
    errors = {}
    if not valid_email(data["email"]):
        errors["email"] = "Enter a valid email address."
    if not data["password"]:
        errors["password"] = "Enter your password."
    return data, errors


def validate_profile(form):
    data = _strip(form, "full_name", "phone")
    data["phone"] = clean_phone(data["phone"])
    errors = {}
    _check_name(data, errors)
    if data["phone"] and not valid_phone(data["phone"]):
        errors["phone"] = "Enter a Cambodian phone number, e.g. 012 345 678."
    return data, errors


def validate_password(form):
    """Shape checks only; Better Auth verifies the current password."""
    data = {"current_password": form.get("current_password") or "", "new_password": form.get("new_password") or ""}
    errors = {}
    if not data["current_password"]:
        errors["current_password"] = "Enter your current password."
    _check_new_password(data["new_password"], errors, "new_password")
    return data, errors


def validate_address(form):
    data = _strip(form, "receiver_name", "phone", "province", "address")
    data["phone"] = clean_phone(data["phone"])
    data["is_default"] = form.get("is_default") == "on"
    errors = {}
    _check_name(data, errors, "receiver_name", "the receiver's name")
    if not valid_phone(data["phone"]):
        errors["phone"] = "Enter a Cambodian phone number, e.g. 012 345 678."
    if data["province"] not in PROVINCES:
        errors["province"] = "Choose a province or city."
    if not data["address"]:
        errors["address"] = "Enter the address details."
    elif len(data["address"]) > 300:
        errors["address"] = "Keep the address under 300 characters."
    return data, errors
