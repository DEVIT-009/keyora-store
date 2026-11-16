"""Catalog queries. Routes call these; templates only ever see the returned models.

Every query that returns products eager-loads variants, because cards read
swatches, price and stock from them. Storefront queries only see published products
(`_published`); the admin has its own queries in app/admin/service.py.
"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Category, Product, ProductVariant

_with_variants = selectinload(Product.variants)
_published = Product.is_published.is_(True)


def get_product(slug):
    """Product with its category and variants, or None."""
    return db.session.scalar(
        select(Product)
        .where(Product.slug == slug, _published)
        .options(joinedload(Product.category), _with_variants)
    )


def best_sellers(limit=4, exclude=()):
    """`exclude` keeps a product from appearing in two homepage rows."""
    # Review count stands in for sales until orders exist.
    stmt = select(Product).order_by(Product.review_count.desc(), Product.id).limit(limit)
    if exclude:
        stmt = stmt.where(Product.id.not_in([p.id for p in exclude]))
    return _products(stmt)


def new_arrivals(limit=4):
    return _products(select(Product).order_by(Product.created_at.desc(), Product.id).limit(limit))


def related_products(product, limit=4):
    """Same category first, then same layout, then the rest of the catalog."""
    return _products(
        select(Product)
        .where(Product.id != product.id)
        .order_by(
            Product.category_id != product.category_id,
            Product.layout.is_distinct_from(product.layout),
            Product.id,
        )
        .limit(limit)
    )


def get_variants(ids):
    """{id: variant} for the given ids, each with its product (and the product's variants) loaded.

    Variants of unpublished products are left out, so they drop out of carts like deleted ones.
    """
    if not ids:
        return {}
    variants = db.session.scalars(
        select(ProductVariant)
        .join(ProductVariant.product)
        .where(ProductVariant.id.in_(ids), _published)
        .options(joinedload(ProductVariant.product).selectinload(Product.variants))
    ).all()
    return {v.id: v for v in variants}


def find_variant(product_id, color=None, switch=None):
    """The variant of a product matching the chosen options; an absent option matches NULL."""
    def matches(column, value):
        return column == value if value else column.is_(None)

    return db.session.scalar(
        select(ProductVariant)
        .join(ProductVariant.product)
        .where(
            _published,
            ProductVariant.product_id == product_id,
            matches(ProductVariant.color_name, color),
            matches(ProductVariant.switch_type, switch),
        )
        .options(joinedload(ProductVariant.product))
    )


def list_categories():
    return db.session.scalars(select(Category).order_by(Category.position)).all()


def categories_with_counts():
    """[(category, product_count)] in menu order, empty categories included."""
    return db.session.execute(
        select(Category, func.count(Product.id))
        .outerjoin(Product, (Product.category_id == Category.id) & _published)
        .group_by(Category.id)
        .order_by(Category.position)
    ).all()


SEARCH_FIELDS = (Product.name, Product.spec, Product.summary, Product.layout, Category.name)


def search_products(query, limit=48):
    """Products where every word of `query` appears (case-insensitive) in the name, tagline,
    summary, layout or category name. Name matches first, then most reviewed."""
    words = query.split()[:8]
    if not words:
        return []
    stmt = select(Product).join(Product.category)
    for word in words:
        stmt = stmt.where(or_(*(_contains(field, word) for field in SEARCH_FIELDS)))
    name_match = _contains(Product.name, words[0])
    return _products(stmt.order_by(name_match.desc(), Product.review_count.desc(), Product.id).limit(limit))


def _contains(column, word):
    """Case-insensitive substring match; LIKE wildcards in `word` (the "%" in "75%") match literally."""
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


def get_category(slug):
    return db.session.scalar(select(Category).where(Category.slug == slug))


def category_products(category, layout=None):
    """Products in a category, most reviewed first; `layout` ("75%") narrows keyboards."""
    stmt = select(Product).where(Product.category_id == category.id)
    if layout:
        stmt = stmt.where(Product.layout == layout)
    return _products(stmt.order_by(Product.review_count.desc(), Product.id))


def layout_counts(category):
    """[(layout, product_count)] for a category, largest board first ("100%" before "60%")."""
    rows = db.session.execute(
        select(Product.layout, func.count())
        .where(Product.category_id == category.id, Product.layout.is_not(None), _published)
        .group_by(Product.layout)
    ).all()
    return sorted(rows, key=lambda row: -_layout_size(row[0]))


def _layout_size(layout):
    try:
        return float(layout.rstrip("%"))
    except ValueError:
        return 0


def _products(stmt):
    """Published products only; every list query above goes through here."""
    return db.session.scalars(stmt.where(_published).options(_with_variants)).all()
