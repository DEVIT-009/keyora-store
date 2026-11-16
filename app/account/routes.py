from urllib.parse import urlsplit

from flask import abort, flash, make_response, redirect, render_template, request, url_for

from app.account import bp, forms, service
from app.auth import AuthUnavailable, clear_auth_cookies, client, current_user, login_required
from app.checkout import orders
from app.checkout.forms import PROVINCES, format_phone

UNAVAILABLE = "We couldn't reach our sign-in service. Please try again in a moment."
TOO_MANY = "Too many attempts. Please wait a minute and try again."

# Better Auth error code -> (field, message). Anything unmapped shows a form-level error.
SIGN_UP_ERRORS = {
    "USER_ALREADY_EXISTS": ("email", "An account with this email already exists."),
    "USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL": ("email", "An account with this email already exists."),
    "INVALID_EMAIL": ("email", "Enter a valid email address."),
    "PASSWORD_TOO_SHORT": ("password", "Use at least 8 characters."),
    "PASSWORD_TOO_LONG": ("password", "Use at most 128 characters."),
}


def _safe_next(target):
    """Only follow same-site relative paths after sign-in (no //evil.com or https://…)."""
    if target and target.startswith("/") and not target.startswith("//") and not urlsplit(target).netloc:
        return target
    return url_for("account.overview")


def _form_error(result):
    return TOO_MANY if result.status == 429 else "Something went wrong. Please try again."


# ---------- Sign up / in / out ----------

@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("account.overview"))
    data, errors, form_error = {}, {}, None
    if request.method == "POST":
        data, errors = forms.validate_register(request.form)
        if not errors:
            try:
                result = client.sign_up(data["full_name"], data["email"], data["password"])
            except AuthUnavailable:
                form_error = UNAVAILABLE
            else:
                if result.ok:
                    flash(f"Welcome to Keyora, {data['full_name'].split()[0]}.", "success")
                    return redirect(_safe_next(request.form.get("next")))
                if result.error in SIGN_UP_ERRORS:
                    field, message = SIGN_UP_ERRORS[result.error]
                    errors[field] = message
                else:
                    form_error = _form_error(result)
    status = 503 if form_error == UNAVAILABLE else 422 if errors or form_error else 200
    return render_template("account/register.html", data=data, errors=errors, form_error=form_error,
                           next=request.values.get("next", "")), status


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("account.overview"))
    data, errors, form_error = {}, {}, None
    if request.method == "POST":
        data, errors = forms.validate_login(request.form)
        if not errors:
            try:
                result = client.sign_in(data["email"], data["password"], data["remember"])
            except AuthUnavailable:
                form_error = UNAVAILABLE
            else:
                if result.ok:
                    return redirect(_safe_next(request.form.get("next")))
                # One message for unknown email and wrong password (Better Auth does the same).
                if result.error == "INVALID_EMAIL_OR_PASSWORD":
                    form_error = "Email or password is incorrect."
                elif result.error == "BANNED_USER":  # blocked in the admin (Better Auth admin plugin)
                    form_error = "This account has been blocked. Contact Keyora support if you think this is a mistake."
                else:
                    form_error = _form_error(result)
    status = 503 if form_error == UNAVAILABLE else 422 if errors or form_error else 200
    return render_template("account/login.html", data=data, errors=errors, form_error=form_error,
                           next=request.values.get("next", "")), status


@bp.post("/logout")
@login_required
def logout():
    flash("You've been signed out.", "info")
    response = make_response(redirect(url_for("main.index")))
    try:
        client.sign_out()
    except AuthUnavailable:
        clear_auth_cookies(response)
    return response


# ---------- Account overview: profile, addresses, password ----------

def _overview(errors=None, data=None, form_error=None, status=200):
    orders.expire_overdue()  # so abandoned QR orders show as expired, not "awaiting payment"
    return render_template("account/overview.html", user=current_user, errors=errors or {}, data=data or {},
                           form_error=form_error, addresses=service.list_addresses(current_user.id),
                           orders=orders.list_for_user(current_user.id), format_phone=format_phone), status


@bp.get("")
@login_required
def overview():
    return _overview()


@bp.post("/profile")
@login_required
def update_profile():
    data, errors = forms.validate_profile(request.form)
    if errors:
        return _overview(errors, data, status=422)
    try:
        result = client.update_user(data["full_name"], data["phone"])
    except AuthUnavailable:
        return _overview(data=data, form_error=UNAVAILABLE, status=503)
    if not result.ok:
        return _overview(data=data, form_error=_form_error(result), status=422)
    flash("Profile saved.", "success")
    return redirect(url_for("account.overview") + "#profile")


@bp.post("/password")
@login_required
def change_password():
    data, errors = forms.validate_password(request.form)
    if errors:
        return _overview(errors, status=422)
    try:
        result = client.change_password(data["current_password"], data["new_password"])
    except AuthUnavailable:
        return _overview(form_error=UNAVAILABLE, status=503)
    if result.error == "INVALID_PASSWORD":
        return _overview({"current_password": "That's not your current password."}, status=422)
    if result.error in ("PASSWORD_TOO_SHORT", "PASSWORD_TOO_LONG"):
        return _overview({"new_password": SIGN_UP_ERRORS[result.error][1]}, status=422)
    if not result.ok:
        return _overview(form_error=_form_error(result), status=422)
    flash("Password changed. Other devices have been signed out.", "success")
    return redirect(url_for("account.overview") + "#security")


# ---------- Addresses ----------

def _own_address(address_id):
    return service.get_address(current_user.id, address_id) or abort(404)


def _address_form(data, errors, address):
    return render_template("account/address_form.html", data=data, errors=errors, address=address,
                           provinces=PROVINCES), 422 if errors else 200


@bp.route("/addresses/new", methods=["GET", "POST"])
@login_required
def new_address():
    data = {"receiver_name": current_user.name, "phone": current_user.phone or "",
            "is_default": not service.list_addresses(current_user.id)}
    errors = {}
    if request.method == "POST":
        data, errors = forms.validate_address(request.form)
        if not errors:
            service.save_address(current_user.id, data)
            flash("Address added.", "success")
            return redirect(url_for("account.overview") + "#addresses")
    return _address_form(data, errors, None)


@bp.route("/addresses/<int:address_id>/edit", methods=["GET", "POST"])
@login_required
def edit_address(address_id):
    address = _own_address(address_id)
    data = {f: getattr(address, f) for f in ("receiver_name", "phone", "province", "address", "is_default")}
    errors = {}
    if request.method == "POST":
        data, errors = forms.validate_address(request.form)
        if not errors:
            service.save_address(current_user.id, data, address)
            flash("Address updated.", "success")
            return redirect(url_for("account.overview") + "#addresses")
    return _address_form(data, errors, address)


@bp.post("/addresses/<int:address_id>/default")
@login_required
def default_address(address_id):
    service.set_default_address(current_user.id, _own_address(address_id))
    flash("Default address updated.", "success")
    return redirect(url_for("account.overview") + "#addresses")


@bp.post("/addresses/<int:address_id>/delete")
@login_required
def delete_address(address_id):
    service.delete_address(current_user.id, _own_address(address_id))
    flash("Address removed.", "info")
    return redirect(url_for("account.overview") + "#addresses")
