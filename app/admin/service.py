"""Admin queries and writes. Routes call these; templates never query.

- Every change records an AdminLog row (`log`) in the same transaction as the change.
- Unlike app/catalog.py, product queries here include drafts.
- Stock edits are applied as deltas (`stock_qty = stock_qty + Δ`), never overwrites, so a
  checkout that reserves stock while the form is open isn't lost.
- Better Auth's "user" / "session" tables are reached through lightweight table() constructs,
  not models, so they stay out of our metadata and Alembic autogenerate. Deleting a user's
  session rows or setting "user".banned takes effect on their next request, because Flask
  re-checks both every time (app/auth/__init__.py `load_current_user`).
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, column, delete, func, or_, select, table, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.auth import current_user
from app.checkout.forms import clean_phone
from app.extensions import db
from app.models import LOW_STOCK_THRESHOLD, AdminLog, Category, Order, Product, ProductVariant

PER_PAGE = 50
STORE_TZ = timezone(timedelta(hours=7))  # Cambodia; "today" on the dashboard starts at local midnight
PAID = ("paid", "paid_late")

users = table("user", column("id"), column("name"), column("email"), column("phone"), column("role"),
              column("createdAt"), column("banned"), column("banReason"), column("banExpires"))
sessions = table("session", column("id"), column("userId"), column("expiresAt"), column("updatedAt"),
                 column("ipAddress"), column("userAgent"))
BLOCK_DURATIONS = {"": "Until unblocked", "1": "1 day", "7": "7 days", "30": "30 days"}


class StockConflict(Exception):
    """A variant's stock changed while the form was open and the edit would take it below 0."""


@dataclass
class Page:
    items: list
    page: int
    pages: int
    total: int

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages


def _paginate(stmt, page, options=(), scalars=True):
    total = db.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    pages = max(math.ceil(total / PER_PAGE), 1)
    page = min(max(page, 1), pages)
    result = db.session.execute(stmt.options(*options).limit(PER_PAGE).offset((page - 1) * PER_PAGE))
    return Page(result.scalars().all() if scalars else result.all(), page, pages, total)


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def log(action, target, **detail):
    """Add an audit row to the current transaction (committed with the change it describes)."""
    db.session.add(AdminLog(user_id=current_user.id, user_email=current_user.email, action=action,
                            target=target, detail=_jsonable(detail)))


def log_now(action, target, **detail):
    """For changes made by helpers that commit themselves (app/checkout/orders.py)."""
    log(action, target, **detail)
    db.session.commit()


def activity(page=1, target=None):
    stmt = select(AdminLog).order_by(AdminLog.created_at.desc(), AdminLog.id.desc())
    if target:
        stmt = stmt.where(AdminLog.target == target)
    return _paginate(stmt, page)


def recent_activity(target, limit=20):
    return db.session.scalars(
        select(AdminLog).where(AdminLog.target == target).order_by(AdminLog.id.desc()).limit(limit)
    ).all()


# ---------- Dashboard ----------

def _count(*where):
    return db.session.scalar(select(func.count()).select_from(Order).where(*where))


def dashboard():
    now = datetime.now(STORE_TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def revenue(since):
        return db.session.execute(
            select(func.coalesce(func.sum(Order.total), 0), func.count())
            .where(Order.status.in_(PAID), Order.paid_at >= since)
        ).one()

    return {
        "attention": {
            "review": _count(Order.review_reason.is_not(None), Order.fulfillment != "refunded"),
            "paid_late": _count(Order.status == "paid_late", Order.fulfillment == "unfulfilled"),
            "to_ship": _count(Order.status == "paid", Order.fulfillment.in_(("unfulfilled", "packed"))),
            "pending": _count(Order.status == "pending"),
        },
        "revenue": [
            ("Today", *revenue(today)),
            ("Last 7 days", *revenue(today - timedelta(days=6))),
            ("Last 30 days", *revenue(today - timedelta(days=29))),
        ],
        "low_stock": db.session.scalars(
            select(ProductVariant)
            .join(ProductVariant.product)
            .where(Product.is_preorder.is_(False), ProductVariant.stock_qty <= LOW_STOCK_THRESHOLD)
            .options(joinedload(ProductVariant.product))
            .order_by(ProductVariant.stock_qty, ProductVariant.id)
            .limit(10)
        ).all(),
        "latest": db.session.scalars(select(Order).order_by(Order.created_at.desc()).limit(8)).all(),
    }


# ---------- Orders ----------

def list_orders(status=None, fulfillment=None, flagged=False, q="", page=1):
    stmt = select(Order).order_by(Order.created_at.desc(), Order.id.desc())
    if status:
        stmt = stmt.where(Order.status == status)
    if fulfillment:
        stmt = stmt.where(Order.fulfillment == fulfillment)
    if flagged:
        stmt = stmt.where(Order.review_reason.is_not(None))
    if q:
        terms = [Order.ref.ilike(f"%{q}%"), Order.email.ilike(f"%{q}%"), Order.receiver_name.ilike(f"%{q}%")]
        if digits := clean_phone(q).lstrip("+"):
            if digits.isdigit():
                terms.append(Order.phone.contains(digits))
        stmt = stmt.where(or_(*terms))
    return _paginate(stmt, page, options=[selectinload(Order.items)])


def get_order(ref):
    return db.session.scalar(select(Order).where(Order.ref == ref).options(selectinload(Order.items)))


def set_staff_note(order, note):
    order.staff_note = note
    log("order.note", f"order:{order.ref}")
    db.session.commit()


# ---------- Products ----------

def _stock_total():
    return (
        select(func.coalesce(func.sum(ProductVariant.stock_qty), 0))
        .where(ProductVariant.product_id == Product.id)
        .correlate(Product)
        .scalar_subquery()
    )


def list_products(category_id=None, stock=None, q="", page=1):
    stmt = select(Product).order_by(Product.created_at.desc(), Product.id.desc())
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if q:
        sku_match = select(ProductVariant.id).where(ProductVariant.product_id == Product.id,
                                                    ProductVariant.sku.ilike(f"%{q}%")).exists()
        stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"), Product.slug.ilike(f"%{q}%"), sku_match))
    total = _stock_total()
    in_stock_only = Product.is_preorder.is_(False)
    if stock == "draft":
        stmt = stmt.where(Product.is_published.is_(False))
    elif stock == "preorder":
        stmt = stmt.where(Product.is_preorder.is_(True))
    elif stock == "out_of_stock":
        stmt = stmt.where(in_stock_only, total <= 0)
    elif stock == "low_stock":
        stmt = stmt.where(in_stock_only, total > 0, total <= LOW_STOCK_THRESHOLD)
    elif stock == "in_stock":
        stmt = stmt.where(in_stock_only, total > LOW_STOCK_THRESHOLD)
    return _paginate(stmt, page, options=[selectinload(Product.variants), joinedload(Product.category)])


def get_product(product_id):
    return db.session.scalar(
        select(Product).where(Product.id == product_id)
        .options(selectinload(Product.variants), joinedload(Product.category))
    )


def slug_taken(slug, exclude_id=None):
    stmt = select(Product.id).where(Product.slug == slug)
    if exclude_id:
        stmt = stmt.where(Product.id != exclude_id)
    return db.session.scalar(stmt) is not None


def skus_taken(skus, exclude_product_id=None):
    """SKUs from `skus` already used by other products' variants."""
    if not skus:
        return set()
    stmt = select(ProductVariant.sku).where(ProductVariant.sku.in_(skus))
    if exclude_product_id:
        stmt = stmt.where(ProductVariant.product_id != exclude_product_id)
    return set(db.session.scalars(stmt))


PRODUCT_FIELDS = ("name", "slug", "category_id", "layout", "spec", "summary", "price", "compare_at", "is_new",
                  "rating", "review_count", "is_preorder", "preorder_ships", "gallery", "highlights", "specs",
                  "is_published")
VARIANT_FIELDS = ("sku", "color_name", "color_hex", "switch_type", "price", "compare_at", "position")


def save_product(product, data, variants):
    """Create or update a product and its variants in one transaction. Returns the product.

    Raises StockConflict or IntegrityError (both rolled back; nothing written).
    """
    creating = product is None
    try:
        if creating:
            product = Product()
            db.session.add(product)
        for field in PRODUCT_FIELDS:
            setattr(product, field, data[field])
        existing = {v.id: v for v in product.variants}

        # Removals first, so a kept row can take over a removed row's color/switch combination
        # without tripping the unique options index.
        removed = [existing[v["id"]] for v in variants if v["remove"] and v["id"] in existing]
        for row in removed:
            product.variants.remove(row)
        db.session.flush()

        deltas, stock_log = [], {}
        for v in variants:
            if v["remove"]:
                continue
            row = existing.get(v["id"]) if v["id"] else None
            if v["id"] and row is None:
                raise StockConflict(v["sku"])  # deleted by someone else since the form loaded
            if row is None:
                row = ProductVariant(stock_qty=v["stock"])
                product.variants.append(row)
                stock_log[v["sku"]] = f"new: {v['stock']}"
            else:
                original = v["stock_orig"] if v["stock_orig"] is not None else row.stock_qty
                if delta := v["stock"] - original:
                    deltas.append((row, delta))
                    stock_log[v["sku"]] = f"{delta:+d}"
            for field in VARIANT_FIELDS:
                setattr(row, field, v[field])
        db.session.flush()

        for row, delta in deltas:
            applied = db.session.execute(
                update(ProductVariant)
                .where(ProductVariant.id == row.id, ProductVariant.stock_qty + delta >= 0)
                .values(stock_qty=ProductVariant.stock_qty + delta)
                .execution_options(synchronize_session=False)
            ).rowcount
            if applied != 1:
                raise StockConflict(row.sku)

        log("product.create" if creating else "product.update", f"product:{product.slug}",
            published=product.is_published, removed=[r.sku for r in removed], stock=stock_log)
        db.session.commit()
    except (StockConflict, IntegrityError):
        db.session.rollback()
        raise
    return product


def set_published(product, published):
    product.is_published = published
    log("product.publish" if published else "product.unpublish", f"product:{product.slug}")
    db.session.commit()


def delete_product(product):
    """Order items keep their snapshots; their variant_id becomes NULL (ON DELETE SET NULL)."""
    log("product.delete", f"product:{product.slug}", name=product.name, skus=[v.sku for v in product.variants])
    db.session.delete(product)
    db.session.commit()


# ---------- Categories ----------

def categories_with_counts():
    """[(category, product_count)] in menu order, drafts counted."""
    return db.session.execute(
        select(Category, func.count(Product.id))
        .outerjoin(Category.products)
        .group_by(Category.id)
        .order_by(Category.position, Category.id)
    ).all()


def list_categories():
    return db.session.scalars(select(Category).order_by(Category.position, Category.id)).all()


def get_category(category_id):
    return db.session.get(Category, category_id)


def category_slug_taken(slug, exclude_id=None):
    stmt = select(Category.id).where(Category.slug == slug)
    if exclude_id:
        stmt = stmt.where(Category.id != exclude_id)
    return db.session.scalar(stmt) is not None


def save_category(category, data):
    creating = category is None
    if creating:
        last = db.session.scalar(select(func.max(Category.position)))
        category = Category(position=(last or 0) + 1)
        db.session.add(category)
    old_slug = category.slug
    category.name, category.slug = data["name"], data["slug"]
    log("category.create" if creating else "category.update", f"category:{category.slug}",
        **({"renamed_from": old_slug} if old_slug and old_slug != category.slug else {}))
    db.session.commit()
    return category


def move_category(category, direction):
    """Swap with the neighbour above (-1) or below (+1); positions are renumbered 0..n first."""
    ordered = list_categories()
    for i, c in enumerate(ordered):
        c.position = i
    i = ordered.index(category)
    j = i + direction
    if 0 <= j < len(ordered):
        ordered[i].position, ordered[j].position = j, i
        log("category.move", f"category:{category.slug}", position=j)
    db.session.commit()


def delete_category(category):
    """Only empty categories can go (products.category_id has no cascade). False if not empty."""
    if db.session.scalar(select(func.count()).where(Product.category_id == category.id)):
        return False
    log("category.delete", f"category:{category.slug}", name=category.name)
    db.session.delete(category)
    db.session.commit()
    return True


# ---------- Customers (Better Auth users) ----------

def _customer_columns():
    stats = (
        select(
            Order.user_id,
            func.count().label("orders"),
            func.coalesce(func.sum(case((Order.status.in_(PAID), Order.total), else_=0)), 0).label("spent"),
        )
        .group_by(Order.user_id)
        .subquery()
    )
    stmt = select(
        users.c.id, users.c.name, users.c.email, users.c.phone, users.c.role,
        users.c.createdAt.label("created_at"),
        _blocked().label("blocked"), users.c.banReason.label("ban_reason"), users.c.banExpires.label("ban_expires"),
        func.coalesce(stats.c.orders, 0).label("orders"),
        func.coalesce(stats.c.spent, 0).label("spent"),
    ).select_from(users.outerjoin(stats, stats.c.user_id == users.c.id))
    return stmt


def _blocked():
    """Banned and the ban hasn't run out (Better Auth lifts expired bans at the next sign-in)."""
    return users.c.banned.is_(True) & or_(users.c.banExpires.is_(None), users.c.banExpires > func.now())


def list_customers(q="", role=None, blocked=False, page=1):
    stmt = _customer_columns().order_by(users.c.createdAt.desc())
    if q:
        stmt = stmt.where(or_(users.c.name.ilike(f"%{q}%"), users.c.email.ilike(f"%{q}%")))
    if role:
        stmt = stmt.where(users.c.role == role)
    if blocked:
        stmt = stmt.where(_blocked())
    return _paginate(stmt, page, scalars=False)


def get_customer(user_id):
    return db.session.execute(_customer_columns().where(users.c.id == user_id)).one_or_none()


def customer_orders(user_id):
    return db.session.scalars(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc())
    ).all()


def active_sessions(user_id):
    """Signed-in devices, most recently active first."""
    return db.session.execute(
        select(sessions.c.updatedAt.label("last_active"), sessions.c.ipAddress.label("ip"),
               sessions.c.userAgent.label("user_agent"))
        .where(sessions.c.userId == user_id, sessions.c.expiresAt > func.now())
        .order_by(sessions.c.updatedAt.desc())
    ).all()


def _end_sessions(user_id):
    return db.session.execute(delete(sessions).where(sessions.c.userId == user_id)).rowcount


def sign_out_everywhere(customer):
    """Delete every session of this user; they're signed out on their next request. Returns an
    error message, or None on success."""
    if customer.id == current_user.id:
        return "To sign yourself out, use Sign out in the header."
    ended = _end_sessions(customer.id)
    log("customer.sign_out", f"user:{customer.id}", email=customer.email, sessions=ended)
    db.session.commit()
    return None


def block(customer, reason, days):
    """Ban the user (Better Auth admin plugin columns) and end their sessions. They're signed out
    on their next request and can't sign in until unblocked or the ban runs out. Admins must be
    demoted first, so two admins can't lock each other out."""
    if customer.id == current_user.id:
        return "You can't block yourself."
    if customer.role == "admin":
        return "Remove admin access before blocking this account."
    expires = datetime.now(timezone.utc) + timedelta(days=int(days)) if days else None
    db.session.execute(update(users).where(users.c.id == customer.id)
                       .values(banned=True, banReason=reason or None, banExpires=expires))
    ended = _end_sessions(customer.id)
    log("customer.block", f"user:{customer.id}", email=customer.email, reason=reason,
        until=expires.isoformat() if expires else "unblocked", sessions=ended)
    db.session.commit()
    return None


def unblock(customer):
    db.session.execute(update(users).where(users.c.id == customer.id)
                       .values(banned=False, banReason=None, banExpires=None))
    log("customer.unblock", f"user:{customer.id}", email=customer.email)
    db.session.commit()


def set_role(customer, role):
    """Make a customer an admin or remove it. Returns an error message, or None on success.

    Takes effect on their next request: the role is read from the DB every time.
    """
    if role not in ("user", "admin"):
        return "Unknown role."
    if customer.id == current_user.id:
        return "You can't change your own role."
    if (customer.role or "user") == role:
        return None
    if role != "admin":
        # Lock the admin rows so two admins can't demote each other at the same moment.
        admins = db.session.scalars(select(users.c.id).where(users.c.role == "admin").with_for_update()).all()
        if len(admins) <= 1:
            db.session.rollback()
            return "There must always be at least one admin."
    if role == "admin" and customer.blocked:
        return "Unblock this account first."
    db.session.execute(update(users).where(users.c.id == customer.id).values(role=role))
    log("customer.role", f"user:{customer.id}", email=customer.email, before=customer.role, after=role)
    db.session.commit()
    return None
