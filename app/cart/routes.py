from flask import abort, redirect, render_template, request, url_for

from app import catalog
from app.cart import bp, store
from app.main import data


@bp.get("")
def view():
    cart = store.build_cart()
    return render_template(
        "cart/cart.html",
        cart=cart,
        perks=data.PERKS,
        popular=[] if cart.lines else catalog.best_sellers(),
    )


@bp.post("/add")
def add():
    form = request.form
    variant = None
    if product_id := form.get("product_id", type=int):
        # Resolve from the chosen options, so the form works without the variant script.
        variant = catalog.find_variant(product_id, form.get("color"), form.get("switch"))
    if variant is None and (variant_id := form.get("variant_id", type=int)):
        variant = catalog.get_variants([variant_id]).get(variant_id)
    if variant is None:
        abort(400)

    if not store.add(variant, form.get("quantity", 1, type=int)):
        # Sold out since the page was loaded: back to the product, which now says so.
        return redirect(url_for("main.product", slug=variant.product.slug))
    return redirect(url_for("cart.view"))


@bp.post("/update")
def update():
    variant_id = request.form.get("variant_id", type=int) or abort(400)
    variant = catalog.get_variants([variant_id]).get(variant_id)
    if variant is None:
        store.remove(variant_id)
    else:
        store.set_quantity(variant, request.form.get("quantity", 1, type=int))
    return redirect(url_for("cart.view"))


@bp.post("/remove")
def remove():
    store.remove(request.form.get("variant_id", type=int) or abort(400))
    return redirect(url_for("cart.view"))
