from flask import abort, render_template, request

from app import catalog
from app.main import bp, data


@bp.route("/")
def index():
    new_arrivals = catalog.new_arrivals()
    return render_template(
        "main/index.html",
        hero=data.HERO,
        perks=data.PERKS,
        layouts=data.LAYOUTS,
        best_sellers=catalog.best_sellers(exclude=new_arrivals),
        new_arrivals=new_arrivals,
        switch_feature=data.SWITCH_FEATURE,
        collections=data.COLLECTIONS,
        setup_banner=data.SETUP_BANNER,
        reviews=data.REVIEWS,
    )


@bp.route("/styleguide")
def styleguide():
    return render_template("main/styleguide.html")


@bp.route("/search")
def search():
    query = " ".join(request.args.get("q", "").split())[:100]
    return render_template(
        "main/search.html",
        query=query,
        results=catalog.search_products(query) if query else [],
        latest=[] if query else catalog.new_arrivals(limit=8),
        categories=catalog.list_categories(),
    )


@bp.route("/categories")
def categories():
    categories = catalog.categories_with_counts()
    keyboards = catalog.get_category("keyboards")
    return render_template(
        "main/categories.html",
        categories=categories,
        total=sum(count for _, count in categories),
        layouts=catalog.layout_counts(keyboards) if keyboards else [],
        layout_images={layout["size"]: layout["image"] for layout in data.LAYOUTS},
        best_sellers=catalog.best_sellers(),
        category_art=data.category_art,
    )


@bp.route("/categories/<slug>")
def category(slug):
    category = catalog.get_category(slug) or abort(404)
    layouts = catalog.layout_counts(category)
    # An unknown ?layout= shows the whole category rather than an empty page.
    layout = request.args.get("layout")
    if layout not in {name for name, _ in layouts}:
        layout = None
    return render_template(
        "main/category.html",
        category=category,
        art=data.category_art(category.slug),
        categories=catalog.list_categories(),
        layouts=layouts,
        layout=layout,
        products=catalog.category_products(category, layout),
    )


@bp.route("/products/<slug>")
def product(slug):
    product = catalog.get_product(slug) or abort(404)
    return render_template(
        "main/product.html",
        product=product,
        perks=data.PERKS,
        related=catalog.related_products(product),
    )
