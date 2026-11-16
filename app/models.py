"""Catalog models (categories, products, variants), saved customer addresses and orders.

Customer accounts themselves live in Better Auth's tables (auth-server/), not here.

Templates read products through the properties below (`stock`, `badge`, `swatches`,
`switches`, `image`, …), which keep the same names the sample data used. Queries live
in app/catalog.py, not here.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

LOW_STOCK_THRESHOLD = 5


def stock_status(qty, preorder=False):
    """One of "preorder" | "out_of_stock" | "low_stock" | "in_stock" (drives badge, stock line, buy button)."""
    if preorder:
        return "preorder"
    if qty <= 0:
        return "out_of_stock"
    return "low_stock" if qty <= LOW_STOCK_THRESHOLD else "in_stock"


class Category(db.Model):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(default=0)

    products: Mapped[list["Product"]] = relationship(back_populates="category")

    def __repr__(self):
        return f"<Category {self.slug}>"


class Product(db.Model):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("compare_at IS NULL OR compare_at > price", name="compare_at_above_price"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    layout: Mapped[str | None] = mapped_column(String(20))  # "75%"; keyboards only
    spec: Mapped[str] = mapped_column(String(200), default="")  # card tagline
    summary: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    compare_at: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    is_new: Mapped[bool] = mapped_column(default=False)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))  # display only until reviews exist
    review_count: Mapped[int] = mapped_column(default=0)
    is_preorder: Mapped[bool] = mapped_column(default=False)
    preorder_ships: Mapped[str | None] = mapped_column(String(80))  # "mid-January"
    gallery: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)  # Unsplash photo IDs or "cld:<public_id>" uploads (app/images.py)
    highlights: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # json (not jsonb) so the spec table keeps its key order.
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    # Drafts and hidden products are left out of every storefront query (app/catalog.py).
    is_published: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    category: Mapped[Category] = relationship(back_populates="products")
    variants: Mapped[list["ProductVariant"]] = relationship(
        back_populates="product", order_by="ProductVariant.position", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Product {self.slug}>"

    @property
    def image(self):
        return self.gallery[0] if self.gallery else None

    @property
    def swatches(self):
        """Distinct (name, hex) colors in variant order."""
        seen = {}
        for v in self.variants:
            if v.color_name:
                seen.setdefault(v.color_name, v.color_hex)
        return list(seen.items())

    @property
    def switches(self):
        return list(dict.fromkeys(v.switch_type for v in self.variants if v.switch_type))

    @property
    def stock_qty(self):
        return sum(v.stock_qty for v in self.variants)

    @property
    def stock(self):
        return stock_status(self.stock_qty, self.is_preorder)

    @property
    def min_price(self):
        return min((v.effective_price for v in self.variants), default=self.price)

    @property
    def has_price_range(self):
        return len({v.effective_price for v in self.variants}) > 1

    @property
    def min_compare_at(self):
        """Compare-at price of the cheapest variant, for the card's strike-through."""
        cheapest = min(self.variants, key=lambda v: v.effective_price, default=None)
        return cheapest.effective_compare_at if cheapest else self.compare_at

    @property
    def badge(self):
        """Merchandising badge; the product_badge macro still overrides it with "soldout"."""
        if self.is_preorder:
            return "preorder"
        if any(v.effective_compare_at for v in self.variants):
            return "sale"
        return "new" if self.is_new else None

    @property
    def default_variant(self):
        """First variant that can be bought, so the page renders a sensible selection without JS."""
        return next((v for v in self.variants if v.stock != "out_of_stock"), None) or (
            self.variants[0] if self.variants else None
        )

    def variants_json(self):
        return [v.as_json() for v in self.variants]


class ProductVariant(db.Model):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("stock_qty >= 0", name="stock_qty_non_negative"),
        CheckConstraint("price IS NULL OR price >= 0", name="price_non_negative"),
        # One row per color/switch combination. coalesce() stands in for NULLS NOT DISTINCT (Postgres 15+).
        Index(
            "uq_product_variants_options", "product_id",
            text("coalesce(color_name, '')"), text("coalesce(switch_type, '')"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    position: Mapped[int] = mapped_column(default=0)
    color_name: Mapped[str | None] = mapped_column(String(40))
    color_hex: Mapped[str | None] = mapped_column(String(7))
    switch_type: Mapped[str | None] = mapped_column(String(40))
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # NULL = product price
    compare_at: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # NULL = product compare_at
    stock_qty: Mapped[int] = mapped_column(default=0, server_default="0")

    product: Mapped[Product] = relationship(back_populates="variants")

    def __repr__(self):
        return f"<ProductVariant {self.sku}>"

    @property
    def effective_price(self):
        return self.price if self.price is not None else self.product.price

    @property
    def effective_compare_at(self):
        compare_at = self.compare_at if self.compare_at is not None else self.product.compare_at
        return compare_at if compare_at and compare_at > self.effective_price else None

    @property
    def stock(self):
        return stock_status(self.stock_qty, self.product.is_preorder)

    def as_json(self):
        return {
            "id": self.id,
            "sku": self.sku,
            "color": self.color_name,
            "switch": self.switch_type,
            "price": str(self.effective_price),
            "compare_at": str(self.effective_compare_at) if self.effective_compare_at else None,
            "stock": self.stock,
            "stock_qty": self.stock_qty,
        }


class Address(db.Model):
    __tablename__ = "addresses"
    __table_args__ = (
        # At most one default address per user.
        Index("uq_addresses_one_default_per_user", "user_id", unique=True, postgresql_where=text("is_default")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Better Auth's "user".id (text). The FK + ON DELETE CASCADE is created in the migration:
    # that table is owned by Better Auth, not this metadata.
    user_id: Mapped[str] = mapped_column(Text, index=True)
    receiver_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(16))
    province: Mapped[str] = mapped_column(String(40))
    address: Mapped[str] = mapped_column(String(300))
    is_default: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    def __repr__(self):
        return f"<Address {self.id}>"


ORDER_STATUSES = ("pending", "paid", "expired", "cancelled", "paid_late")
# Shipping progress, separate from payment `status` (which only Bakong can move to paid).
# `refunded` = staff refunded a paid_late / flagged order by bank transfer instead of shipping.
FULFILLMENT_STATUSES = ("unfulfilled", "packed", "shipped", "delivered", "refunded")


class Order(db.Model):
    """A placed checkout, paid by KHQR. Queries and state changes live in app/checkout/orders.py.

    `pending` → `paid` only through a conditional update after Bakong confirms the payment;
    `pending` → `expired` / `cancelled` release reserved stock; a payment found for an
    expired/cancelled order makes it `paid_late` (staff fulfil or refund by bank transfer).
    """

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in ORDER_STATUSES) + ")", name="status_valid"
        ),
        CheckConstraint("subtotal >= 0 AND savings >= 0 AND shipping >= 0 AND total >= 0", name="amounts_non_negative"),
        CheckConstraint(
            "fulfillment IN (" + ", ".join(f"'{s}'" for s in FULFILLMENT_STATUSES) + ")", name="fulfillment_valid"
        ),
        Index("ix_orders_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(25), unique=True)  # also the KHQR bill number (tag 62/01)
    # Better Auth's "user".id; NULL for guests. FK (ON DELETE SET NULL) is created in the migration.
    user_id: Mapped[str | None] = mapped_column(Text, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")

    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str] = mapped_column(String(16))
    receiver_name: Mapped[str] = mapped_column(String(80))
    province: Mapped[str] = mapped_column(String(40), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    delivery: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(500), default="")

    currency: Mapped[str] = mapped_column(String(3))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    savings: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal(0))
    shipping: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    # The exact string shown to the customer; its md5 is how Bakong identifies the payment.
    khqr_string: Mapped[str] = mapped_column(Text)
    khqr_md5: Mapped[str] = mapped_column(String(32), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bakong_hash: Mapped[str | None] = mapped_column(Text, unique=True)  # one transaction settles one order
    payer_account: Mapped[str | None] = mapped_column(Text)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    review_reason: Mapped[str | None] = mapped_column(Text)  # payment found but didn't verify; never auto-paid

    # Set by staff in the admin (app/checkout/orders.py `set_fulfillment`).
    fulfillment: Mapped[str] = mapped_column(String(16), default="unfulfilled", server_default="unfulfilled")
    tracking: Mapped[str] = mapped_column(String(120), default="", server_default="")
    staff_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", order_by="OrderItem.id", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Order {self.ref} {self.status}>"

    @property
    def is_expired(self):
        return datetime.now(timezone.utc) >= self.expires_at


class OrderItem(db.Model):
    """One cart line, with what was shown and charged at the time (product data can change later)."""

    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id", ondelete="SET NULL"), index=True)
    product_slug: Mapped[str] = mapped_column(String(120))
    product_name: Mapped[str] = mapped_column(String(120))
    options: Mapped[str] = mapped_column(String(100), default="")
    sku: Mapped[str] = mapped_column(String(64))
    image: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int]
    # Stock was taken for this line (False for pre-orders); only reserved quantities are given back.
    reserved: Mapped[bool] = mapped_column(default=True, server_default="true")

    order: Mapped[Order] = relationship(back_populates="items")

    def __repr__(self):
        return f"<OrderItem {self.sku} × {self.quantity}>"

    @property
    def total(self):
        return self.unit_price * self.quantity


class AdminLog(db.Model):
    """Append-only record of every change made in the admin (who, what, on which row)."""

    __tablename__ = "admin_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(Text)  # Better Auth "user".id; no FK so the log outlives the account
    user_email: Mapped[str] = mapped_column(String(254))
    action: Mapped[str] = mapped_column(String(40))  # "order.fulfillment", "product.update", …
    target: Mapped[str] = mapped_column(String(160), index=True)  # "order:KY-…", "product:slug", "user:<id>"
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), index=True
    )

    def __repr__(self):
        return f"<AdminLog {self.action} {self.target}>"
