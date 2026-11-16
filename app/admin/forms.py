"""Admin form parsing and validation. Each validate_* returns (cleaned data, {field: message}).

Checks mirror the DB constraints (prices, compare-at, unique SKU / slug / options) so staff
see field errors instead of an IntegrityError. Uniqueness against other rows is checked in
app/admin/service.py, which can query.
"""

import re
from decimal import Decimal, InvalidOperation

from app import cloudinary

MAX_PRICE = Decimal("99999999.99")  # Numeric(10, 2)
MAX_STOCK = 1_000_000

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Unsplash photo id as stored ("1618384887929-16ec33fab9ef"); a pasted
# images.unsplash.com/photo-… URL is reduced to it.
_PHOTO_ID = re.compile(r"^\d{10,}-[0-9a-f]{6,}$")
_PHOTO_URL = re.compile(r"images\.unsplash\.com/photo-([0-9]+-[0-9a-f]+)")
# Cloudinary upload as stored by app/cloudinary.py ("cld:keyora/products/abc123").
_CLOUDINARY_ID = re.compile(r"^cld:[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")
_VARIANT_KEY = re.compile(r"^variants-(\d+)-(\w+)$")

VARIANT_FIELDS = ("id", "sku", "color_name", "color_hex", "switch_type", "price", "compare_at", "stock", "stock_orig",
                  "position", "remove")
# Keyboard layouts staff can pick (value stored in products.layout, label shown in the select).
# Sizes match the storefront's layout filter chips and homepage tiles (app/main/data.py LAYOUTS).
LAYOUTS = {"100%": "100% · Full size", "96%": "96% · 1800 compact", "80%": "80% · Tenkeyless (TKL)",
           "75%": "75% · Compact", "65%": "65%", "60%": "60%", "40%": "40%"}
STOCK_FILTERS = {"in_stock": "In stock", "low_stock": "Low stock", "out_of_stock": "Sold out",
                 "preorder": "Pre-order", "draft": "Drafts"}


def layout_choices(current=None):
    """LAYOUTS plus the product's current value if it isn't one of them, so old data still saves."""
    return LAYOUTS if not current or current in LAYOUTS else {**LAYOUTS, current: current}


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:120]


def _strip(form, *names):
    return {name: (form.get(name) or "").strip() for name in names}


def _lines(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _money(raw, errors, field, required=False):
    """Decimal with 2 places, or None when blank and optional."""
    if not raw:
        if required:
            errors[field] = "Enter a price."
        return None
    try:
        value = Decimal(raw.replace("$", "").replace(",", ""))
    except InvalidOperation:
        errors[field] = "Enter an amount like 169 or 169.50."
        return None
    if not value.is_finite() or value < 0 or value > MAX_PRICE:
        errors[field] = "Enter an amount of 0 or more."
        return None
    if value != value.quantize(Decimal("0.01")):
        errors[field] = "Use at most 2 decimal places."
        return None
    return value.quantize(Decimal("0.01"))


def _int(raw, errors, field, default=0, maximum=MAX_STOCK):
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        errors[field] = "Enter a whole number."
        return default
    if not 0 <= value <= maximum:
        errors[field] = f"Enter a number from 0 to {maximum:,}."
        return default
    return value


def photo_id(raw):
    """Stored photo id for a Cloudinary upload, a pasted Unsplash id or images.unsplash.com URL, or None."""
    raw = raw.strip()
    if raw.startswith("cld:"):
        return raw if _CLOUDINARY_ID.match(raw) else None
    if match := _PHOTO_URL.search(raw):
        return match.group(1)
    raw = raw.removeprefix("photo-")
    return raw if _PHOTO_ID.match(raw) else None


# ---------- Products ----------

def validate_product(form, category_ids, new_photos=0, layouts=LAYOUTS):
    """`new_photos` = valid files waiting to be uploaded; they count towards "has a photo".
    `layouts` = allowed layout values (`layout_choices()`)."""
    data = _strip(form, "name", "slug", "layout", "spec", "summary", "preorder_ships")
    data["slug"] = data["slug"].lower() or slugify(data["name"])
    for flag in ("is_new", "is_preorder", "is_published"):
        data[flag] = form.get(flag) == "on"
    errors = {}

    if not data["name"]:
        errors["name"] = "Enter the product name."
    elif len(data["name"]) > 120:
        errors["name"] = "Keep the name under 120 characters."
    if not _SLUG.match(data["slug"]):
        errors["slug"] = "Use lowercase letters, numbers and hyphens, e.g. aster-75-wireless."
    elif len(data["slug"]) > 120:
        errors["slug"] = "Keep the slug under 120 characters."

    data["category_id"] = form.get("category_id", type=int)
    if data["category_id"] not in category_ids:
        errors["category_id"] = "Choose a category."
    if data["layout"] and data["layout"] not in layouts:
        errors["layout"] = "Choose a layout from the list."
    data["layout"] = data["layout"] or None
    if len(data["spec"]) > 200:
        errors["spec"] = "Keep the tagline under 200 characters."
    if data["is_preorder"] and not data["preorder_ships"]:
        errors["preorder_ships"] = "Say when pre-orders ship, e.g. mid-January."
    elif len(data["preorder_ships"]) > 80:
        errors["preorder_ships"] = "Keep this under 80 characters."
    data["preorder_ships"] = data["preorder_ships"] or None

    data["price"] = _money(form.get("price", "").strip(), errors, "price", required=True)
    data["compare_at"] = _money(form.get("compare_at", "").strip(), errors, "compare_at")
    if data["compare_at"] is not None and data["price"] is not None and data["compare_at"] <= data["price"]:
        errors["compare_at"] = "The compare-at price must be higher than the price (leave blank for no sale)."

    rating = form.get("rating", "").strip()
    data["rating"] = None
    if rating:
        try:
            data["rating"] = Decimal(rating).quantize(Decimal("0.1"))
            if not 0 <= data["rating"] <= 5:
                raise InvalidOperation
        except InvalidOperation:
            errors["rating"] = "Enter a rating from 0 to 5."
    data["review_count"] = _int(form.get("review_count", "").strip(), errors, "review_count")

    # Gallery: one photo id (Unsplash id/URL or cld: upload) per line; order is the display order.
    # New uploads are appended after save (app/admin/routes.py).
    data["gallery_raw"] = form.get("gallery", "")
    gallery, bad = [], []
    for line in _lines(data["gallery_raw"]):
        (gallery.append if (pid := photo_id(line)) else bad.append)(pid or line)
    data["gallery"] = list(dict.fromkeys(gallery))
    if bad:
        errors["gallery"] = f"Not a photo id: {bad[0]}"
    elif data["is_published"] and not data["gallery"] and not new_photos:
        errors["gallery"] = "Add at least one photo before publishing."

    data["highlights"] = _lines(form.get("highlights", ""))

    # Specs: parallel key/value rows; blank keys are dropped, order is kept (JSON column).
    data["spec_rows"] = list(zip(form.getlist("spec_key"), form.getlist("spec_value")))
    specs = {}
    for key, value in data["spec_rows"]:
        key, value = key.strip(), value.strip()
        if key:
            specs[key] = value
    data["specs"] = specs
    return data, errors


def validate_photos(files):
    """WebP bytes for each chosen file (nothing is uploaded yet), or an error for the first bad one."""
    files = [f for f in files if f and f.filename]
    if not files:
        return [], {}
    if not cloudinary.configured():
        return [], {"photos": "Photo uploads aren't set up. Add the CLOUDINARY_* settings to .env."}
    if len(files) > cloudinary.MAX_FILES:
        return [], {"photos": f"Upload at most {cloudinary.MAX_FILES} photos at a time."}
    try:
        return [cloudinary.to_webp(f) for f in files], {}
    except cloudinary.BadImage as exc:
        return [], {"photos": str(exc)}


def parse_variant_rows(form):
    """[{field: raw str}] from `variants-<i>-<field>` inputs, in index order. Fully blank new rows are dropped."""
    rows = {}
    for key in form:
        if match := _VARIANT_KEY.match(key):
            index, name = int(match.group(1)), match.group(2)
            if name in VARIANT_FIELDS:
                rows.setdefault(index, {})[name] = (form.get(key) or "").strip()
    result = []
    for index in sorted(rows):
        row = {name: rows[index].get(name, "") for name in VARIANT_FIELDS}
        if not row["id"] and not any(row[n] for n in ("sku", "color_name", "switch_type", "price", "compare_at", "stock")):
            continue
        result.append(row)
    return result


def validate_variants(rows, product_price, require_one):
    """Cleaned variants, in form order. Errors are keyed `variants-<n>-<field>` by row position."""
    errors, variants, seen_skus, seen_options = {}, [], set(), set()
    for n, row in enumerate(rows):
        key = f"variants-{n}-"
        v = {
            "id": int(row["id"]) if row["id"].isdigit() else None,
            "remove": row["remove"] == "on",
            "sku": row["sku"].upper(),
            "color_name": row["color_name"] or None,
            "switch_type": row["switch_type"] or None,
            "position": n,
        }
        if v["remove"]:
            variants.append(v)
            continue
        v["color_hex"] = row["color_hex"] if v["color_name"] else None
        if not v["sku"]:
            errors[key + "sku"] = "Enter a SKU."
        elif len(v["sku"]) > 64:
            errors[key + "sku"] = "Keep the SKU under 64 characters."
        elif v["sku"] in seen_skus:
            errors[key + "sku"] = "Each variant needs its own SKU."
        seen_skus.add(v["sku"])
        if v["color_name"] and not _HEX.match(v["color_hex"] or ""):
            errors[key + "color_hex"] = "Pick a swatch color."
        if len(v["color_name"] or "") > 40 or len(v["switch_type"] or "") > 40:
            errors[key + "color_name"] = "Keep option names under 40 characters."
        options = ((v["color_name"] or "").lower(), (v["switch_type"] or "").lower())
        if options in seen_options:
            errors[key + "color_name"] = "Another variant already has this color and switch."
        seen_options.add(options)

        v["price"] = _money(row["price"], errors, key + "price")
        v["compare_at"] = _money(row["compare_at"], errors, key + "compare_at")
        effective = v["price"] if v["price"] is not None else product_price
        if v["compare_at"] is not None and effective is not None and v["compare_at"] <= effective:
            errors[key + "compare_at"] = "Must be higher than the variant's price."
        v["stock"] = _int(row["stock"], errors, key + "stock")
        v["stock_orig"] = int(row["stock_orig"]) if row["stock_orig"].lstrip("-").isdigit() else None
        variants.append(v)
    if require_one and not any(not v["remove"] for v in variants):
        errors["variants"] = "Add at least one variant before publishing."
    return variants, errors


# ---------- Categories ----------

def validate_category(form):
    data = _strip(form, "name", "slug")
    data["slug"] = data["slug"].lower() or slugify(data["name"])[:80]
    errors = {}
    if not data["name"]:
        errors["name"] = "Enter the category name."
    elif len(data["name"]) > 80:
        errors["name"] = "Keep the name under 80 characters."
    if not _SLUG.match(data["slug"]) or len(data["slug"]) > 80:
        errors["slug"] = "Use lowercase letters, numbers and hyphens, e.g. desk-mats."
    return data, errors


# ---------- Orders ----------

def validate_tracking(form):
    tracking = (form.get("tracking") or "").strip()
    return tracking, ({"tracking": "Keep tracking under 120 characters."} if len(tracking) > 120 else {})


def validate_note(form):
    note = (form.get("staff_note") or "").strip()
    return note, ({"staff_note": "Keep the note under 2,000 characters."} if len(note) > 2000 else {})


# ---------- Customers ----------

def validate_block(form, durations):
    data = {"reason": (form.get("reason") or "").strip(), "days": form.get("days") or ""}
    errors = {}
    if len(data["reason"]) > 200:
        errors["reason"] = "Keep the reason under 200 characters."
    if data["days"] not in durations:
        errors["days"] = "Choose how long to block."
    return data, errors
