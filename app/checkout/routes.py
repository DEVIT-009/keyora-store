import logging

from flask import flash, make_response, redirect, render_template, request, session, url_for

from app.auth import current_user
from app.cart import store
from app.checkout import bakong, bp, forms, khqr, orders

log = logging.getLogger(__name__)


def _render(cart, data, errors=None, status=200, unavailable=False):
    method = data.get("delivery") or "delivery"
    return render_template(
        "checkout/checkout.html",
        cart=cart,
        data=data,
        errors=errors or {},
        forms=forms,
        delivery_fee=forms.shipping_fee("delivery", cart.subtotal),
        shipping=forms.shipping_fee(method, cart.subtotal),
        unavailable=unavailable,
    ), status


def _no_store(response):
    """Pay/order pages and status answers must never be cached (shared or browser)."""
    response = make_response(response)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("")
def view():
    cart = store.build_cart()
    if not cart.can_checkout:
        return redirect(url_for("cart.view"))
    return _render(cart, {"delivery": "delivery", "payment": "khqr"})


@bp.post("")
def place_order():
    cart = store.build_cart()
    if not cart.can_checkout:
        return redirect(url_for("cart.view"))

    data, errors = forms.validate(request.form)
    if errors:
        return _render(cart, data, errors, status=422)

    try:
        order = orders.create(cart, data, user_id=current_user.id)
    except orders.OutOfStock:
        flash("Sorry, an item in your cart sold out while you were checking out. Your cart has been updated.", "info")
        return redirect(url_for("cart.view"))
    except khqr.KHQRError as exc:
        log.error("KHQR not configured correctly: %s", exc)
        return _render(cart, data, status=503, unavailable=True)

    orders.remember(order)
    session.pop(store.SESSION_KEY, None)
    return redirect(url_for("checkout.pay", ref=order.ref))


def _load(ref):
    """The viewer's order, expired first (DB only) if its QR is past expiry + grace."""
    order = orders.get_for_viewer(ref)
    if order.status == "pending" and orders.is_overdue(order):
        orders.expire(order)
    return order


@bp.get("/pay/<ref>")
def pay(ref):
    order = _load(ref)
    if order.status != "pending":
        return redirect(url_for("checkout.order", ref=ref))
    return _no_store(render_template(
        "checkout/pay.html",
        order=order,
        qr_image=khqr.image_data_uri(order.khqr_string),
        forms=forms,
    ))


@bp.post("/pay/<ref>/check")
def check(ref):
    """The "I've paid" button: the only route that asks Bakong. It never marks paid by itself."""
    order = orders.get_for_viewer(ref)
    try:
        status = orders.confirm(order)
    except orders.CheckTooSoon:
        flash("Still checking your payment. Wait a few seconds, then try again.", "info")
        return redirect(url_for("checkout.pay", ref=ref))
    except bakong.BakongUnavailable:
        flash("We couldn't reach the bank to confirm your payment. Please try again in a moment.", "info")
        return redirect(url_for("checkout.pay", ref=ref))
    if status == "pending":
        flash("We haven't received the payment yet. It can take a few seconds after you pay. Try again shortly.", "info")
        return redirect(url_for("checkout.pay", ref=ref))
    if status in ("expired", "cancelled"):
        flash("We couldn't find a payment for this order.", "info")
    return redirect(url_for("checkout.order", ref=ref))


@bp.post("/pay/<ref>/cancel")
def cancel(ref):
    """DB only. If they had paid after all, "I already paid" on the order page finds it (paid_late)."""
    order = orders.get_for_viewer(ref)
    if orders.cancel(order):
        flash(f"Order {ref} was cancelled.", "info")
    return redirect(url_for("checkout.order", ref=ref))


@bp.get("/orders/<ref>")
def order(ref):
    order = _load(ref)
    if order.status == "pending":
        return redirect(url_for("checkout.pay", ref=ref))
    return _no_store(render_template("checkout/order.html", order=order, forms=forms))
