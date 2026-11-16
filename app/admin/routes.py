"""Admin pages: dashboard, orders, products, categories, customers, activity log.

Access is checked once for the whole blueprint (app/admin/__init__.py). Every write is a
POST that redirects (post/redirect/get) or re-renders its form with 422.
"""

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from app import cloudinary
from app.account import service as addresses
from app.admin import bp, forms, service
from app.auth import current_user
from app.checkout import bakong, orders
from app.checkout import forms as checkout_forms
from app.models import FULFILLMENT_STATUSES, ORDER_STATUSES

STATUS_LABELS = {
    "pending": "Awaiting payment", "paid": "Paid", "paid_late": "Paid late",
    "expired": "Expired", "cancelled": "Cancelled",
}
FULFILLMENT_LABELS = {
    "unfulfilled": "Unfulfilled", "packed": "Packed", "shipped": "Shipped",
    "delivered": "Delivered", "refunded": "Refunded",
}


@bp.context_processor
def _admin_context():
    return {
        "STATUS_LABELS": STATUS_LABELS,
        "FULFILLMENT_LABELS": FULFILLMENT_LABELS,
        "format_phone": checkout_forms.format_phone,
        "local_time": lambda dt: dt.astimezone(service.STORE_TZ),
        "device": _device,
        "ACCOUNT_ACTIONS": ACCOUNT_ACTIONS,
    }


ACCOUNT_ACTIONS = {
    "customer.role": "Role changed", "customer.sign_out": "Signed out everywhere",
    "customer.block": "Blocked", "customer.unblock": "Unblocked",
}


def _device(user_agent):
    """"Chrome on macOS" from a User-Agent string; good enough to tell sessions apart."""
    ua = user_agent or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari")) if key in ua), "Browser")
    system = next((name for key, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                                          ("Mac OS X", "macOS"), ("Windows", "Windows"), ("Linux", "Linux")) if key in ua), "")
    return f"{browser} on {system}" if system else browser


def _page():
    return request.args.get("page", 1, type=int)


# ---------- Dashboard ----------

@bp.get("")
def dashboard():
    orders.expire_overdue()  # DB only: stale pending orders show as expired, stock released
    return render_template("admin/dashboard.html", stats=service.dashboard(), nav="dashboard")


@bp.get("/activity")
def activity():
    return render_template("admin/activity.html", page=service.activity(_page(), request.args.get("target")),
                           target=request.args.get("target"), nav="activity")


# ---------- Orders ----------

@bp.get("/orders")
def order_list():
    orders.expire_overdue()
    args = request.args
    status = args.get("status") if args.get("status") in ORDER_STATUSES else None
    fulfillment = args.get("fulfillment") if args.get("fulfillment") in FULFILLMENT_STATUSES else None
    flagged = args.get("flagged") == "1"
    q = args.get("q", "").strip()
    return render_template(
        "admin/orders.html",
        page=service.list_orders(status, fulfillment, flagged, q, _page()),
        status=status, fulfillment=fulfillment, flagged=flagged, q=q,
        statuses=ORDER_STATUSES, fulfillments=FULFILLMENT_STATUSES, nav="orders",
    )


def _order(ref):
    return service.get_order(ref) or abort(404)


def _render_order(order, errors=None, status=200):
    if order.status == "pending" and orders.is_overdue(order):
        orders.expire(order)
    return render_template(
        "admin/order.html", order=order, errors=errors or {}, forms=checkout_forms,
        next_step=orders.next_fulfillment(order), can_refund=orders.can_refund(order),
        history=service.recent_activity(f"order:{order.ref}"), nav="orders",
    ), status


@bp.get("/orders/<ref>")
def order_detail(ref):
    return _render_order(_order(ref))


@bp.post("/orders/<ref>/fulfillment")
def order_fulfillment(ref):
    order = _order(ref)
    to = request.form.get("to")
    tracking, errors = forms.validate_tracking(request.form)
    if errors:
        return _render_order(order, errors, 422)
    before = order.fulfillment
    if orders.set_fulfillment(order, to, tracking if to == "shipped" else None):
        service.log_now("order.fulfillment", f"order:{order.ref}", before=before, after=to,
                        **({"tracking": tracking} if to == "shipped" and tracking else {}))
        flash(f"Order {ref} marked {FULFILLMENT_LABELS[to].lower()}.", "success")
    else:
        flash("That step isn't available for this order any more. The page shows its current state.", "info")
    return redirect(url_for("admin.order_detail", ref=ref))


@bp.post("/orders/<ref>/note")
def order_note(ref):
    order = _order(ref)
    note, errors = forms.validate_note(request.form)
    if errors:
        return _render_order(order, errors, 422)
    service.set_staff_note(order, note)
    flash("Note saved.", "success")
    return redirect(url_for("admin.order_detail", ref=ref) + "#note")


@bp.post("/orders/<ref>/check")
def order_check(ref):
    """Ask Bakong, exactly like the customer's "I've paid" button (same throttle and checks)."""
    order = _order(ref)
    before = order.status
    try:
        status = orders.confirm(order)
    except orders.CheckTooSoon:
        flash("This order was checked a moment ago. Wait a few seconds, then try again.", "info")
    except bakong.BakongUnavailable:
        flash("Couldn't reach Bakong. Nothing was changed; try again shortly.", "info")
    else:
        service.log_now("order.check", f"order:{order.ref}", before=before, after=status)
        if status != before:
            flash(f"Bakong check: order is now {STATUS_LABELS[status].lower()}.", "success")
        elif order.review_reason:
            flash(f"A payment was found but didn't verify: {order.review_reason}", "info")
        else:
            flash("Bakong has no payment for this order.", "info")
    return redirect(url_for("admin.order_detail", ref=ref))


@bp.post("/orders/<ref>/cancel")
def order_cancel(ref):
    order = _order(ref)
    if orders.cancel(order):
        service.log_now("order.cancel", f"order:{order.ref}")
        flash(f"Order {ref} cancelled and its stock released.", "success")
    else:
        flash("Only orders awaiting payment can be cancelled.", "info")
    return redirect(url_for("admin.order_detail", ref=ref))


# ---------- Products ----------

@bp.get("/products")
def product_list():
    args = request.args
    category_id = args.get("category", type=int)
    stock = args.get("stock") if args.get("stock") in forms.STOCK_FILTERS else None
    q = args.get("q", "").strip()
    return render_template(
        "admin/products.html",
        page=service.list_products(category_id, stock, q, _page()),
        categories=service.list_categories(), category_id=category_id, stock=stock, q=q,
        stock_filters=forms.STOCK_FILTERS, nav="products",
    )


def _product(product_id):
    return service.get_product(product_id) or abort(404)


def _product_form(product, data, variants, errors, status=200):
    return render_template(
        "admin/product_form.html", product=product, data=data, variants=variants, errors=errors,
        categories=service.list_categories(), nav="products", uploads=cloudinary.configured(),
        layouts=forms.layout_choices(product and product.layout),
        accept=cloudinary.ACCEPT, max_files=cloudinary.MAX_FILES,
    ), status


def _form_from_product(product):
    data = {f: getattr(product, f) for f in service.PRODUCT_FIELDS}
    data["gallery_raw"] = "\n".join(product.gallery or [])
    data["highlights"] = product.highlights or []
    data["spec_rows"] = list((product.specs or {}).items())
    variants = [
        {"id": v.id, "sku": v.sku, "color_name": v.color_name, "color_hex": v.color_hex,
         "switch_type": v.switch_type, "price": v.price, "compare_at": v.compare_at,
         "stock": v.stock_qty, "stock_orig": v.stock_qty, "remove": False}
        for v in product.variants
    ]
    return data, variants


def _save_product(product):
    """Validate and save the posted form; returns a response either way."""
    categories = service.list_categories()
    photos, photo_errors = forms.validate_photos(request.files.getlist("photos"))
    data, errors = forms.validate_product(request.form, {c.id for c in categories}, new_photos=len(photos),
                                          layouts=forms.layout_choices(product and product.layout))
    errors.update(photo_errors)
    rows = forms.parse_variant_rows(request.form)
    variants, variant_errors = forms.validate_variants(rows, data["price"], require_one=data["is_published"])
    errors.update(variant_errors)
    if "slug" not in errors and service.slug_taken(data["slug"], product and product.id):
        errors["slug"] = "Another product already uses this slug."
    kept = [v for v in variants if not v["remove"]]
    for sku in service.skus_taken({v["sku"] for v in kept if v["sku"]}, product and product.id):
        n = next(i for i, v in enumerate(variants) if v.get("sku") == sku)
        errors.setdefault(f"variants-{n}-sku", "Another product already uses this SKU.")
    if errors and photos:
        data["photos_note"] = "Your photos weren't uploaded because of the errors above. Choose them again."
    elif photos:
        _upload_photos(photos, data, errors)
    if not errors:
        try:
            saved = service.save_product(product, data, variants)
        except service.StockConflict as exc:
            errors["variants"] = (f"Stock for {exc.args[0]} changed while you were editing (an order may have "
                                  "reserved it). Reload the page to see current stock, then save again.")
        except IntegrityError:
            errors["variants"] = "Two variants can't share the same SKU or color + switch combination."
        else:
            flash(f"{saved.name} {'created' if product is None else 'saved'}.", "success")
            return redirect(url_for("admin.product_edit", product_id=saved.id))
        if product is not None:
            product = service.get_product(product.id)  # reloaded after the rollback
    return _product_form(product, data, rows_for_form(rows, variants), errors, 422)


def _upload_photos(photos, data, errors):
    """Upload to Cloudinary only once the rest of the form is valid, appending to the gallery.

    The gallery text is rewritten with the new ids, so if the save still fails (stock conflict,
    or a later upload fails) the re-rendered form keeps the photos that did upload.
    """
    for done, webp in enumerate(photos):
        try:
            data["gallery"].append(cloudinary.upload(webp))
        except cloudinary.CloudinaryUnavailable:
            errors["photos"] = (f"Uploaded {done} of {len(photos)} photos; Cloudinary didn't accept the rest. "
                                "Nothing was saved. Choose the remaining photos and save again.")
            break
    data["gallery_raw"] = "\n".join(data["gallery"])


def rows_for_form(rows, variants):
    """Re-render posted rows as typed, keeping the original stock so a retry still applies a delta."""
    return [{**row, "remove": v["remove"]} for row, v in zip(rows, variants)]


@bp.route("/products/new", methods=["GET", "POST"])
def product_new():
    if request.method == "POST":
        return _save_product(None)
    data = {"is_published": False, "spec_rows": [], "highlights": [], "gallery_raw": ""}
    return _product_form(None, data, [], {})


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def product_edit(product_id):
    product = _product(product_id)
    if request.method == "POST":
        return _save_product(product)
    data, variants = _form_from_product(product)
    return _product_form(product, data, variants, {})


@bp.post("/products/<int:product_id>/publish")
def product_publish(product_id):
    product = _product(product_id)
    publish = request.form.get("publish") == "1"
    if publish and (not product.variants or not product.gallery):
        flash("Add at least one photo and one variant before publishing.", "info")
        return redirect(url_for("admin.product_edit", product_id=product.id))
    service.set_published(product, publish)
    flash(f"{product.name} is {'live' if publish else 'hidden from the store'}.", "success")
    if request.form.get("back") == "list":
        return redirect(url_for("admin.product_list"))
    return redirect(url_for("admin.product_edit", product_id=product.id))


@bp.post("/products/<int:product_id>/delete")
def product_delete(product_id):
    product = _product(product_id)
    if request.form.get("confirm") != product.slug:
        flash(f"Type {product.slug} to confirm deleting this product.", "info")
        return redirect(url_for("admin.product_edit", product_id=product.id) + "#delete")
    name = product.name
    service.delete_product(product)
    flash(f"{name} deleted. Past orders keep their item details.", "success")
    return redirect(url_for("admin.product_list"))


# ---------- Categories ----------

def _categories_page(data=None, errors=None, editing=None, status=200):
    return render_template(
        "admin/categories.html", categories=service.categories_with_counts(), data=data or {},
        errors=errors or {}, editing=editing, nav="categories",
    ), status


@bp.get("/categories")
def category_list():
    return _categories_page()


def _save_category(category):
    data, errors = forms.validate_category(request.form)
    if "slug" not in errors and service.category_slug_taken(data["slug"], category and category.id):
        errors["slug"] = "Another category already uses this slug."
    if errors:
        return _categories_page(data, errors, category, 422)
    saved = service.save_category(category, data)
    flash(f"Category {saved.name} {'added' if category is None else 'saved'}.", "success")
    return redirect(url_for("admin.category_list"))


@bp.post("/categories")
def category_create():
    return _save_category(None)


@bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
def category_edit(category_id):
    category = service.get_category(category_id) or abort(404)
    if request.method == "POST":
        return _save_category(category)
    return _categories_page({"name": category.name, "slug": category.slug}, editing=category)


@bp.post("/categories/<int:category_id>/move")
def category_move(category_id):
    category = service.get_category(category_id) or abort(404)
    service.move_category(category, -1 if request.form.get("direction") == "up" else 1)
    return redirect(url_for("admin.category_list"))


@bp.post("/categories/<int:category_id>/delete")
def category_delete(category_id):
    category = service.get_category(category_id) or abort(404)
    if service.delete_category(category):
        flash(f"Category {category.name} deleted.", "success")
    else:
        flash(f"{category.name} still has products. Move or delete them first.", "info")
    return redirect(url_for("admin.category_list"))


# ---------- Customers ----------

@bp.get("/customers")
def customer_list():
    q = request.args.get("q", "").strip()
    role = request.args.get("role") if request.args.get("role") in ("user", "admin") else None
    blocked = request.args.get("status") == "blocked"
    return render_template("admin/customers.html", page=service.list_customers(q, role, blocked, _page()),
                           q=q, role=role, blocked=blocked, nav="customers")


def _customer(user_id):
    return service.get_customer(user_id) or abort(404)


def _render_customer(customer, errors=None, data=None, status=200):
    return render_template(
        "admin/customer.html", customer=customer, orders=service.customer_orders(customer.id),
        addresses=addresses.list_addresses(customer.id), sessions=service.active_sessions(customer.id),
        is_self=customer.id == current_user.id, history=service.recent_activity(f"user:{customer.id}"),
        durations=service.BLOCK_DURATIONS, errors=errors or {}, data=data or {}, nav="customers",
    ), status


@bp.get("/customers/<user_id>")
def customer_detail(user_id):
    return _render_customer(_customer(user_id))


def _back_to_customer(user_id):
    return redirect(url_for("admin.customer_detail", user_id=user_id) + "#access")


@bp.post("/customers/<user_id>/sign-out")
def customer_sign_out(user_id):
    customer = _customer(user_id)
    if error := service.sign_out_everywhere(customer):
        flash(error, "info")
    else:
        flash(f"{customer.email} has been signed out on every device.", "success")
    return _back_to_customer(user_id)


@bp.post("/customers/<user_id>/block")
def customer_block(user_id):
    customer = _customer(user_id)
    data, errors = forms.validate_block(request.form, service.BLOCK_DURATIONS)
    if errors:
        return _render_customer(customer, errors, data, 422)
    if error := service.block(customer, data["reason"], data["days"]):
        flash(error, "info")
    else:
        flash(f"{customer.email} is blocked and has been signed out.", "success")
    return _back_to_customer(user_id)


@bp.post("/customers/<user_id>/unblock")
def customer_unblock(user_id):
    customer = _customer(user_id)
    service.unblock(customer)
    flash(f"{customer.email} is unblocked and can sign in again.", "success")
    return _back_to_customer(user_id)


@bp.post("/customers/<user_id>/role")
def customer_role(user_id):
    customer = _customer(user_id)
    role = request.form.get("role")
    if error := service.set_role(customer, role):
        flash(error, "info")
    else:
        flash(f"{customer.email} is now {'an admin' if role == 'admin' else 'a customer'}.", "success")
    return _back_to_customer(user_id)
