"""Order queries and state changes for KHQR checkout.

Rules (see the khqr-bakong skill):
- Amount, currency and account come from the cart re-priced from the DB and from config,
  never from the request.
- Only a verified Bakong answer marks an order paid: the receiving account, currency and
  amount must match, and `bakong_hash` is UNIQUE so one transfer can't settle two orders.
- Bakong is asked only when the customer clicks "I've paid" (`confirm`) — no polling and
  no background sweep. Overdue orders are expired by a DB-only update (`expire_overdue`).
  Trade-off: a customer who pays and never clicks leaves the order unsettled although the
  money arrived; clicking later (even on an expired order) still finds it.
- Every status change is a conditional UPDATE on the current status, so double clicks,
  cancel and the expiry sweep can race safely; side effects (stock release, logging) run
  only for the caller whose UPDATE matched.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import abort, current_app, session
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.auth import current_user
from app.checkout import bakong, forms, khqr
from app.extensions import db
from app.models import Order, OrderItem, ProductVariant

log = logging.getLogger(__name__)

SESSION_KEY = "orders"  # refs this browser placed, so guests can reopen their pay/order pages
SESSION_LIMIT = 10
CHECK_INTERVAL = timedelta(seconds=3)  # at most one Bakong call per order per interval
# Pending orders stay open this long after the QR expires, so a customer who paid right at
# the deadline can still click "I've paid" and get `paid` rather than `paid_late`.
EXPIRY_GRACE = timedelta(minutes=5)

_REF_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: no I, L, O, U


class OutOfStock(Exception):
    """A line couldn't be reserved; nothing was written."""


class CheckTooSoon(Exception):
    """This order was checked with Bakong less than CHECK_INTERVAL ago."""


def _now():
    return datetime.now(timezone.utc)


def _new_ref():
    return "KY-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))


# --- Lookup -------------------------------------------------------------------------

def get_for_viewer(ref):
    """The order if this browser placed it or it belongs to the signed-in user; 404 otherwise."""
    order = db.session.scalar(select(Order).where(Order.ref == ref).options(selectinload(Order.items)))
    if order is None:
        abort(404)
    owns = current_user.is_authenticated and order.user_id == current_user.id
    if not owns and ref not in session.get(SESSION_KEY, []):
        abort(404)
    return order


def list_for_user(user_id, limit=20):
    """A signed-in customer's orders (any status), newest first, with their items."""
    return db.session.scalars(
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
        .options(selectinload(Order.items))
    ).all()


def remember(order):
    refs = [r for r in session.get(SESSION_KEY, []) if r != order.ref]
    session[SESSION_KEY] = (refs + [order.ref])[-SESSION_LIMIT:]


# --- Create -------------------------------------------------------------------------

def create(cart, data, user_id=None):
    """Reserve stock, insert the order + items and its KHQR, in one transaction.

    Raises OutOfStock (nothing written) or khqr.KHQRError (misconfigured merchant).
    """
    expire_overdue()  # return abandoned reservations first, so their stock can be bought
    config = current_app.config
    shipping = forms.shipping_fee(data["delivery"], cart.subtotal)
    total = cart.subtotal + shipping
    created_at = _now()
    expires_at = created_at + timedelta(minutes=config["KHQR_EXPIRATION_MINUTES"])
    ref = _new_ref()
    qr, md5 = khqr.build(
        account_id=config["BAKONG_ACCOUNT_ID"],
        merchant_name=config["MERCHANT_NAME"],
        merchant_city=config["MERCHANT_CITY"],
        currency=config["KHQR_CURRENCY"],
        amount=total,
        bill_number=ref,
        created_at=created_at,
        expires_at=expires_at,
        mobile_number=config["MERCHANT_PHONE"],
        store_label=config["STORE_LABEL"],
        terminal_label=config["TERMINAL_LABEL"],
    )

    order = Order(
        ref=ref, user_id=user_id, status="pending",
        email=data["email"], phone=data["phone"], receiver_name=data["receiver_name"],
        province=data["province"], address=data["address"], delivery=data["delivery"], note=data["note"],
        currency=config["KHQR_CURRENCY"], subtotal=cart.subtotal, savings=cart.savings,
        shipping=shipping, total=total,
        khqr_string=qr, khqr_md5=md5, expires_at=expires_at, created_at=created_at,
    )
    for line in cart.lines:
        reserve = not line.product.is_preorder
        if reserve:
            # Conditional decrement: two checkouts for the last unit can't both succeed.
            taken = db.session.execute(
                update(ProductVariant)
                .where(ProductVariant.id == line.variant.id, ProductVariant.stock_qty >= line.quantity)
                .values(stock_qty=ProductVariant.stock_qty - line.quantity)
                .execution_options(synchronize_session=False)
            ).rowcount
            if taken != 1:
                db.session.rollback()
                raise OutOfStock(line.variant.sku)
        order.items.append(OrderItem(
            variant_id=line.variant.id, product_slug=line.product.slug, product_name=line.product.name,
            options=line.options, sku=line.variant.sku, image=line.product.image,
            unit_price=line.unit_price, quantity=line.quantity, reserved=reserve,
        ))
    db.session.add(order)
    db.session.commit()
    log.info("Order %s placed: %s %s, expires %s", ref, total, order.currency, expires_at.isoformat())
    return order


# --- Settlement ---------------------------------------------------------------------

def _to_amount(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _verify(order, data):
    """None if Bakong's transaction matches the order, else the reason."""
    if data.get("toAccountId") != current_app.config["BAKONG_ACCOUNT_ID"]:
        return f"paid to {data.get('toAccountId')!r}, not our account"
    if data.get("currency") != order.currency:
        return f"currency {data.get('currency')!r} != {order.currency}"
    try:
        amount = _to_amount(data.get("amount"))
    except ArithmeticError:
        return f"unreadable amount {data.get('amount')!r}"
    if amount != order.total:
        return f"amount {amount} != {order.total}"
    if not data.get("hash"):
        return "no transaction hash"
    return None


def _flag(order, reason):
    log.warning("Order %s payment needs review: %s", order.ref, reason)
    db.session.execute(update(Order).where(Order.id == order.id).values(review_reason=reason))
    db.session.commit()


def _claim_check(order):
    """Record a Bakong check; False if another request checked within CHECK_INTERVAL."""
    now = _now()
    claimed = db.session.execute(
        update(Order)
        .where(Order.id == order.id, or_(Order.last_checked_at.is_(None), Order.last_checked_at < now - CHECK_INTERVAL))
        .values(last_checked_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.session.commit()
    return claimed == 1


def _record_payment(order, data, from_statuses, to_status):
    """Conditional transition; True only for the caller that made it."""
    reason = _verify(order, data)
    if reason:
        _flag(order, reason)
        return False
    try:
        won = db.session.execute(
            update(Order)
            .where(Order.id == order.id, Order.status.in_(from_statuses))
            .values(
                status=to_status, paid_at=_now(), bakong_hash=data["hash"],
                payer_account=data.get("fromAccountId"), paid_amount=_to_amount(data["amount"]),
                review_reason=None,
            )
            .returning(Order.id)
            .execution_options(synchronize_session=False)
        ).scalar() is not None
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        _flag(order, f"transaction {data['hash']} already settled another order")
        return False
    db.session.refresh(order)
    if won:
        log.info("Order %s %s via Bakong %s", order.ref, to_status, data["hash"])
    return won


def confirm(order):
    """The "I've paid" button — the only place Bakong is asked. Returns the order's status.

    Raises CheckTooSoon (throttled) or BakongUnavailable (couldn't ask; nothing changed).
    A payment found for an expired/cancelled order makes it `paid_late`.
    """
    if order.status in ("paid", "paid_late"):
        return order.status
    if not _claim_check(order):
        raise CheckTooSoon
    data = bakong.check_md5(order.khqr_md5)
    if data is None:
        if order.status == "pending" and is_overdue(order):
            expire(order)
        return order.status
    if order.status == "pending":
        # Still pending means stock is still held, so a payment just after expiry is fine.
        _record_payment(order, data, ("pending",), "paid")
    else:
        mark_paid_late(order, data)
    return order.status


def mark_paid_late(order, data):
    """Payment found for an expired/cancelled order. Stock isn't re-reserved: staff fulfil or refund."""
    if _record_payment(order, data, ("expired", "cancelled"), "paid_late"):
        log.warning("Order %s was paid after it closed: fulfil or refund by bank transfer", order.ref)


def _close(order, status):
    """pending → expired/cancelled and give back reserved stock, once."""
    won = db.session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == "pending")
        .values(status=status)
        .returning(Order.id)
        .execution_options(synchronize_session=False)
    ).scalar() is not None
    if won:
        for item in order.items:
            if item.reserved and item.variant_id:
                db.session.execute(
                    update(ProductVariant)
                    .where(ProductVariant.id == item.variant_id)
                    .values(stock_qty=ProductVariant.stock_qty + item.quantity)
                    .execution_options(synchronize_session=False)
                )
        log.info("Order %s %s; stock released", order.ref, status)
    db.session.commit()
    db.session.refresh(order)
    return won


def expire(order):
    return _close(order, "expired")


def cancel(order):
    return _close(order, "cancelled")


def is_overdue(order):
    return _now() >= order.expires_at + EXPIRY_GRACE


def expire_overdue():
    """Expire every pending order past its QR expiry + grace and release its stock. DB only."""
    overdue = db.session.scalars(
        select(Order)
        .where(Order.status == "pending", Order.expires_at < _now() - EXPIRY_GRACE)
        .options(selectinload(Order.items))
    ).all()
    return sum(expire(order) for order in overdue)


# --- Fulfillment (staff, from the admin) ----------------------------------------------
# Separate from payment `status`: staff move a paid order forward one step at a time.
# Nothing here can make an order paid.

FULFILLMENT_NEXT = {"unfulfilled": "packed", "packed": "shipped", "shipped": "delivered"}


def next_fulfillment(order):
    """The step staff can move this order to next, or None (not paid, or already delivered/refunded)."""
    if order.status not in ("paid", "paid_late"):
        return None
    return FULFILLMENT_NEXT.get(order.fulfillment)


def can_refund(order):
    """Money arrived but the order shouldn't ship as-is: paid after closing, or flagged for review."""
    return (order.status == "paid_late" or bool(order.review_reason)) and order.fulfillment in ("unfulfilled", "packed")


def set_fulfillment(order, to, tracking=None):
    """Move fulfillment one allowed step (or to `refunded`). Conditional on the current value,
    so two staff clicking at once can't skip or repeat a step. True only for the caller that moved it."""
    from_ = order.fulfillment
    if to == "refunded":
        allowed = can_refund(order)
    else:
        allowed = to == next_fulfillment(order)
    if not allowed:
        return False
    values = {"fulfillment": to}
    if to == "shipped":
        values["shipped_at"] = _now()
        if tracking is not None:
            values["tracking"] = tracking
    elif to == "delivered":
        values["delivered_at"] = _now()
    won = db.session.execute(
        update(Order)
        .where(Order.id == order.id, Order.fulfillment == from_)
        .values(**values)
        .returning(Order.id)
        .execution_options(synchronize_session=False)
    ).scalar() is not None
    db.session.commit()
    db.session.refresh(order)
    if won:
        log.info("Order %s fulfillment %s -> %s", order.ref, from_, to)
    return won
