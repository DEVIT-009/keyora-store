"""Session-backed cart.

The session holds only `[[variant_id, quantity], ...]` (a list, so lines keep the
order they were added; Flask sorts dict keys when serialising). Prices and stock
are always read fresh from the catalog, never stored.
"""

from dataclasses import dataclass
from decimal import Decimal

from flask import session

from app import catalog

SESSION_KEY = "cart"
FREE_SHIPPING_THRESHOLD = Decimal("99")
PREORDER_LIMIT = 10  # same cap the product page quantity input uses


def max_quantity(variant):
    """How many of this variant one cart line may hold; 0 means it can't be bought."""
    return PREORDER_LIMIT if variant.product.is_preorder else variant.stock_qty


def _items():
    """{variant_id: quantity} in insertion order, ignoring anything malformed."""
    items = {}
    for entry in session.get(SESSION_KEY, []):
        try:
            variant_id, quantity = int(entry[0]), int(entry[1])
        except (TypeError, ValueError, IndexError):
            continue
        if quantity > 0:
            items[variant_id] = quantity
    return items


def _save(items):
    session[SESSION_KEY] = [[vid, qty] for vid, qty in items.items() if qty > 0]


def count():
    return sum(_items().values())


def add(variant, quantity=1):
    """Add to the variant's line, clamped to what's available. Returns False if it can't be bought."""
    limit = max_quantity(variant)
    if limit <= 0:
        return False
    items = _items()
    items[variant.id] = min(items.get(variant.id, 0) + max(quantity, 1), limit)
    _save(items)
    return True


def set_quantity(variant, quantity):
    items = _items()
    if variant.id not in items:
        return
    if quantity <= 0:
        items.pop(variant.id)
    else:
        items[variant.id] = min(quantity, max(max_quantity(variant), 1))
    _save(items)


def remove(variant_id):
    items = _items()
    if items.pop(variant_id, None) is not None:
        _save(items)


@dataclass
class CartLine:
    variant: object
    quantity: int
    max_qty: int

    @property
    def product(self):
        return self.variant.product

    @property
    def unavailable(self):
        return self.max_qty <= 0

    @property
    def options(self):
        return " · ".join(o for o in (self.variant.color_name, self.variant.switch_type) if o)

    @property
    def unit_price(self):
        return self.variant.effective_price

    @property
    def total(self):
        return self.unit_price * self.quantity

    @property
    def savings(self):
        compare_at = self.variant.effective_compare_at
        return (compare_at - self.unit_price) * self.quantity if compare_at else Decimal(0)


@dataclass
class Cart:
    lines: list

    @property
    def _buyable(self):
        return [line for line in self.lines if not line.unavailable]

    @property
    def item_count(self):
        return sum(line.quantity for line in self._buyable)

    @property
    def subtotal(self):
        return sum((line.total for line in self._buyable), Decimal(0))

    @property
    def savings(self):
        return sum((line.savings for line in self._buyable), Decimal(0))

    @property
    def free_shipping_remaining(self):
        return max(FREE_SHIPPING_THRESHOLD - self.subtotal, Decimal(0))

    @property
    def free_shipping_progress(self):
        """0–100, for the progress bar."""
        return min(int(self.subtotal / FREE_SHIPPING_THRESHOLD * 100), 100)

    @property
    def has_unavailable(self):
        return any(line.unavailable for line in self.lines)

    @property
    def can_checkout(self):
        return bool(self.lines) and not self.has_unavailable


def build_cart():
    """Cart with current prices/stock. Drops deleted variants and clamps over-stock quantities."""
    items = _items()
    variants = catalog.get_variants(list(items))
    lines, changed = [], False
    for variant_id, quantity in items.items():
        variant = variants.get(variant_id)
        if variant is None:
            changed = True
            continue
        limit = max_quantity(variant)
        if 0 < limit < quantity:
            quantity, changed = limit, True
        lines.append(CartLine(variant, quantity, limit))
    if changed:
        _save({line.variant.id: line.quantity for line in lines})
    return Cart(lines)
