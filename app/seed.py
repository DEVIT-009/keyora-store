"""Sample catalog, loaded with `flask --app run seed`. Safe to re-run: rows are upserted by slug / SKU.

Each product gets one variant per color × switch. `stock` lists the quantity of each
variant in that order (colors outer, switches inner). `variant_prices` overrides the
product price for a switch type. Omit `swatches` / `switches` when a product has no such
option (switch packs, keycap sets without colorways, …).
"""

from datetime import datetime, timedelta, timezone

import click
from sqlalchemy import select

from app.extensions import db
from app.models import Category, Product, ProductVariant

CATEGORIES = [
    ("keyboards", "Keyboards"),
    ("switches", "Switches"),
    ("keycaps", "Keycaps"),
    ("accessories", "Accessories"),
]

PRODUCTS = [
    {
        "name": "Aster 75 Wireless", "category": "keyboards", "layout": "75%",
        "spec": "75% · Gasket mount · Tri-mode",
        "price": 169, "is_new": True, "rating": 4.9, "review_count": 312,
        "gallery": ["1618384887929-16ec33fab9ef", "1632079003110-d694908500da", "1777259113729-9bda92fb8ce8", "1604964432806-254d07c11f32"],
        "swatches": [("Carbon", "#2b2c2e"), ("Fog", "#c9c9c6"), ("Harbor", "#8fa3b8")],
        "switches": ["Linear", "Tactile", "Silent linear"],
        "stock": [12, 10, 6, 8, 7, 0, 9, 6, 4],
        "variant_prices": {"Silent linear": 179},
        "summary": "A gasket-mounted 75% board with a CNC aluminum case, tri-mode wireless and a sound profile tuned out of the box.",
        "highlights": ["Bluetooth 5.1, 2.4 GHz and wired USB-C", "South-facing, hot-swappable 5-pin sockets", "4,000 mAh battery, up to 200 hours"],
        "specs": {"Layout": "75% (84 keys)", "Case": "6063 aluminum", "Mount": "Gasket", "Connectivity": "Bluetooth / 2.4 GHz / USB-C", "Keycaps": "Double-shot PBT, OSA profile", "Weight": "1.6 kg"},
    },
    {
        "name": "Aster 65 Aluminum", "category": "keyboards", "layout": "65%",
        "spec": "65% · Hot-swap · QMK",
        "price": 129, "compare_at": 149, "rating": 4.8, "review_count": 528,
        "gallery": ["1589578228447-e1a4e481c6c8", "1625130694338-4110ba634e59", "1626958390898-162d3577f293", "1592683855405-3f272c7e462a"],
        "swatches": [("Carbon", "#2b2c2e"), ("Sand", "#d8d4cc")],
        "switches": ["Linear", "Tactile"],
        "stock": [2, 1, 0, 0],
        "summary": "Everything you need in a compact frame: arrow keys, a solid aluminum shell and full QMK/VIA remapping.",
        "highlights": ["Remap every key in the browser with VIA", "Double-gasket design with sound-dampening foam", "Detachable braided USB-C cable included"],
        "specs": {"Layout": "65% (68 keys)", "Case": "6063 aluminum", "Mount": "Double gasket", "Connectivity": "USB-C wired", "Keycaps": "Double-shot PBT, Cherry profile", "Weight": "1.4 kg"},
    },
    {
        "name": "Heritage TKL", "category": "keyboards", "layout": "80%",
        "spec": "80% · Retro PBT keycaps",
        "price": 189, "rating": 4.7, "review_count": 141,
        "gallery": ["1760708551859-6559dc9640b8", "1606075014584-5ccf554b50db", "1612538811009-ed19118a2b53"],
        "swatches": [("Ivory", "#e6dccb"), ("Teal", "#5f8f86")],
        "switches": ["Tactile", "Clicky"],
        "stock": [10, 8, 7, 5],
        "summary": "A tenkeyless board with a nod to classic terminals: warm ivory keycaps, a sculpted profile and a satisfying, rounded sound.",
        "highlights": ["Dye-sublimated PBT keycaps that never shine", "Steel plate for a crisp, firm feel", "Adjustable two-stage feet"],
        "specs": {"Layout": "80% (87 keys)", "Case": "ABS with steel plate", "Mount": "Top mount", "Connectivity": "USB-C wired", "Keycaps": "Dye-sub PBT, SA-style profile", "Weight": "1.2 kg"},
    },
    {
        "name": "Mono 60", "category": "keyboards", "layout": "60%",
        "spec": "60% · Ultra compact",
        "price": 99, "rating": 4.6, "review_count": 207,
        "gallery": ["1637243218672-d338945efdf7", "1538481199705-c710c4e965fc", "1584727151652-d09b17ebf23f"],
        "swatches": [("Carbon", "#1d1e1f"), ("Chalk", "#f2f2f0")],
        "switches": ["Linear", "Tactile"],
        "stock": [0, 0, 0, 0],
        "summary": "The minimum number of keys and the maximum amount of desk space. A dense, heavy 60% that travels well.",
        "highlights": ["Function layer for arrows, media and F-row", "Fits in a sleeve with a laptop", "Hot-swappable 5-pin sockets"],
        "specs": {"Layout": "60% (61 keys)", "Case": "Aluminum", "Mount": "Tray mount", "Connectivity": "USB-C wired", "Keycaps": "Double-shot PBT, Cherry profile", "Weight": "0.9 kg"},
    },
    {
        "name": "Petal 65", "category": "keyboards", "layout": "65%",
        "spec": "65% · Silent linear switches",
        "price": 149, "rating": 4.9, "review_count": 64,
        "is_preorder": True, "preorder_ships": "mid-January",
        "gallery": ["1712396901531-605f06a423aa", "1558050032-160f36233a07", "1601445638532-3c6f6c3aa1d6"],
        "swatches": [("Blush", "#f4d6d2"), ("Chalk", "#f2f2f0")],
        "switches": ["Silent linear"],
        "stock": [0, 0],
        "summary": "Soft colors and silent switches for shared spaces. Quiet enough for late-night typing next to someone sleeping.",
        "highlights": ["Factory-lubed silent linear switches", "Poron and IXPE foam layers", "Tri-mode wireless with 3 device pairing"],
        "specs": {"Layout": "65% (68 keys)", "Case": "Polycarbonate", "Mount": "Gasket", "Connectivity": "Bluetooth / 2.4 GHz / USB-C", "Keycaps": "Dye-sub PBT, MDA profile", "Weight": "1.0 kg"},
    },
    {
        "name": "Coastline 75", "category": "keyboards", "layout": "75%",
        "spec": "75% · Brass weight · Knob",
        "price": 209, "rating": 4.8, "review_count": 98,
        "gallery": ["1648392368628-6e984d89e2f3", "1595225386386-79c3543adbd9", "1627509493009-9249a2ad2459"],
        "swatches": [("Seafoam", "#b7d3d8"), ("Carbon", "#2b2c2e")],
        "switches": ["Linear", "Tactile", "Clicky"],
        "stock": [2, 1, 1, 1, 0, 0],
        "summary": "Our heaviest 75%, with a polished brass weight and a programmable rotary knob for volume, zoom or scrubbing.",
        "highlights": ["Programmable aluminum rotary knob", "Polished brass bottom weight", "Per-key south-facing RGB"],
        "specs": {"Layout": "75% (82 keys + knob)", "Case": "6063 aluminum, brass weight", "Mount": "Gasket", "Connectivity": "USB-C wired", "Keycaps": "Double-shot PBT, Cherry profile", "Weight": "2.1 kg"},
    },
    {
        "name": "Frost 60", "category": "keyboards", "layout": "60%",
        "spec": "60% · Polycarbonate case",
        "price": 119, "compare_at": 139, "rating": 4.5, "review_count": 173,
        "gallery": ["1628676633339-81fc485c635c", "1697022976749-35bac4eb77dc", "1619683322755-4545503f1afa"],
        "swatches": [("Frost", "#f2f2f0")],
        "switches": ["Linear", "Tactile"],
        "stock": [15, 9],
        "summary": "A frosted polycarbonate case that diffuses the backlight into a soft glow. Light, bright and easy to carry.",
        "highlights": ["Frosted case with diffused RGB underglow", "Flex-cut PCB for a softer bottom-out", "Hot-swappable 5-pin sockets"],
        "specs": {"Layout": "60% (61 keys)", "Case": "Frosted polycarbonate", "Mount": "Gasket", "Connectivity": "USB-C wired", "Keycaps": "Double-shot PBT, OEM profile", "Weight": "0.8 kg"},
    },
    {
        "name": "Slate 65 HE", "category": "keyboards", "layout": "65%",
        "spec": "65% · Magnetic switches · 8K",
        "price": 179, "is_new": True, "rating": 4.8, "review_count": 86,
        "gallery": ["1768445386364-529daf74c7fe", "1768445386103-81dd131586a2", "1602025882379-e01cf08baa51"],
        "swatches": [("Slate", "#5d6670"), ("Carbon", "#2b2c2e")],
        "switches": ["Magnetic linear"],
        "stock": [11, 7],
        "summary": "Hall-effect magnetic switches with adjustable actuation from 0.1 to 4.0 mm and an 8,000 Hz polling rate for competitive play.",
        "highlights": ["Adjustable actuation per key", "Rapid trigger for instant reset", "8K polling with 0.125 ms latency"],
        "specs": {"Layout": "65% (68 keys)", "Case": "Aluminum", "Mount": "Gasket", "Connectivity": "USB-C wired, 8 kHz", "Keycaps": "Double-shot PBT, Cherry profile", "Weight": "1.5 kg"},
    },
    # --- Switches: sold per pack, one variant each (no color or switch option) ---
    {
        "name": "Glide Linear Switches", "category": "switches",
        "spec": "Linear · 45 gf · 70 pack",
        "price": 32, "rating": 4.8, "review_count": 64,
        "gallery": ["1769237846317-e05700a65390", "1632125972828-a4cfdec70f00", "1723074953141-4ab0a6d9affc"],
        "stock": [40],
        "summary": "Smooth, factory-lubed linears with a light 45 gf actuation and a deep, muted bottom-out. The easiest upgrade for any hot-swap board.",
        "highlights": ["Factory-lubed stems and springs", "5-pin, fits any MX-style hot-swap socket", "Long-pole stem for a crisp, rounded sound"],
        "specs": {"Type": "Linear", "Actuation force": "45 gf", "Total travel": "4.0 mm", "Pins": "5-pin", "Housing": "Polycarbonate top, nylon bottom", "In the box": "70 switches"},
    },
    {
        "name": "Butter Tactile Switches", "category": "switches",
        "spec": "Tactile · 55 gf · 70 pack",
        "price": 35, "rating": 4.7, "review_count": 38,
        "gallery": ["1733296444222-40d9c3d9b8b7", "1733296444250-bd902de8d143"],
        "stock": [4],
        "summary": "A rounded tactile bump right at the top of the press, with no scratch and no click. Made for long writing sessions.",
        "highlights": ["Pronounced bump with a smooth return", "Factory-lubed, no extra tuning needed", "5-pin, fits any MX-style hot-swap socket"],
        "specs": {"Type": "Tactile", "Actuation force": "55 gf", "Total travel": "4.0 mm", "Pins": "5-pin", "Housing": "Nylon", "In the box": "70 switches"},
    },
    {
        "name": "Snap Clicky Switches", "category": "switches",
        "spec": "Clicky · 60 gf · 70 pack",
        "price": 29, "rating": 4.5, "review_count": 22,
        "gallery": ["1733296444174-9fdd9ff7bc43"],
        "stock": [0],
        "summary": "A sharp click-jacket switch with a crisp, audible snap on every press. Loud in the best way.",
        "highlights": ["Click-jacket mechanism for a consistent click", "Tactile bump with an audible snap", "5-pin, fits any MX-style hot-swap socket"],
        "specs": {"Type": "Clicky", "Actuation force": "60 gf", "Total travel": "4.0 mm", "Pins": "5-pin", "Housing": "Polycarbonate", "In the box": "70 switches"},
    },
    {
        "name": "Switch Sampler Pack", "category": "switches",
        "spec": "12 switches · Tester base",
        "price": 19, "rating": 4.9, "review_count": 117,
        "gallery": ["1725386635250-bcbbe18d1654", "1632125972828-a4cfdec70f00"],
        "stock": [25],
        "summary": "Twelve different switches on a tester base, so you can feel linear, tactile and clicky before you buy a full set.",
        "highlights": ["4 linear, 4 tactile and 4 clicky switches", "Weighted acrylic tester base", "Switch puller included"],
        "specs": {"Switches": "12, one of each", "Types": "Linear, tactile, clicky", "Base": "Acrylic", "In the box": "Tester, 12 switches, puller"},
    },
    # --- Keycaps: colorways are the color option ---
    {
        "name": "Pop PBT Keycap Set", "category": "keycaps",
        "spec": "Cherry profile · 135 keys",
        "price": 59, "rating": 4.8, "review_count": 92,
        "gallery": ["1601445638532-3c6f6c3aa1d6", "1558050032-160f36233a07", "1526920929362-5b26677c148c"],
        "swatches": [("Pastel", "#b9d8c9"), ("Sunset", "#f29a8e")],
        "stock": [18, 6],
        "summary": "Bright double-shot PBT in two playful colorways, with enough keys to cover 60% to full-size boards.",
        "highlights": ["Double-shot legends that never fade", "1.5 mm thick PBT, no shine", "Fits 60%, 65%, 75%, TKL and full size"],
        "specs": {"Profile": "Cherry", "Material": "Double-shot PBT", "Thickness": "1.5 mm", "Keys": "135", "Compatibility": "MX-style stems"},
    },
    {
        "name": "Retro Mod Keycaps", "category": "keycaps",
        "spec": "OEM profile · 128 keys",
        "price": 69, "compare_at": 79, "rating": 4.6, "review_count": 47,
        "gallery": ["1526920929362-5b26677c148c", "1601445638532-3c6f6c3aa1d6"],
        "stock": [12],
        "summary": "Grey alphas with primary-colored modifiers, inspired by the computers of the eighties.",
        "highlights": ["Dye-sublimated PBT", "Primary-color modifiers and accents", "Includes extra spacebars"],
        "specs": {"Profile": "OEM", "Material": "Dye-sub PBT", "Thickness": "1.4 mm", "Keys": "128", "Compatibility": "MX-style stems"},
    },
    {
        "name": "Coral Keycap Set", "category": "keycaps",
        "spec": "XDA profile · 140 keys",
        "price": 55, "rating": 4.7, "review_count": 29,
        "gallery": ["1648392368628-6e984d89e2f3"],
        "stock": [14],
        "summary": "Soft mint keys with coral and cobalt accents in a flat, uniform XDA profile.",
        "highlights": ["Uniform XDA profile, every row the same", "Dye-sublimated PBT", "Novelty keys included"],
        "specs": {"Profile": "XDA", "Material": "Dye-sub PBT", "Thickness": "1.5 mm", "Keys": "140", "Compatibility": "MX-style stems"},
    },
    {
        "name": "Blush Keycap Set", "category": "keycaps",
        "spec": "Cherry profile · 129 keys",
        "price": 65, "rating": 4.9, "review_count": 12,
        "is_preorder": True, "preorder_ships": "early February",
        "gallery": ["1712396901531-605f06a423aa"],
        "stock": [0],
        "summary": "Warm white keys with a single coral accent. A quiet, clean look for a bright desk.",
        "highlights": ["Double-shot PBT", "Coral escape and enter keys", "Fits most standard layouts"],
        "specs": {"Profile": "Cherry", "Material": "Double-shot PBT", "Thickness": "1.5 mm", "Keys": "129", "Compatibility": "MX-style stems"},
    },
    # --- Accessories ---
    {
        "name": "Felt Desk Mat", "category": "accessories",
        "spec": "900 × 400 mm · Wool felt",
        "price": 39, "rating": 4.8, "review_count": 76,
        "gallery": ["1702561667800-2c49b0182229", "1650394923482-a0d03ffb2512"],
        "swatches": [("Charcoal", "#3a3b3d"), ("Stone", "#9a9893")],
        "stock": [22, 3],
        "summary": "A dense wool-felt mat that softens typing sound and gives your mouse a smooth, even glide.",
        "highlights": ["4 mm merino wool felt", "Non-slip natural rubber base", "Big enough for a full-size board and mouse"],
        "specs": {"Size": "900 × 400 mm", "Thickness": "4 mm", "Top": "Merino wool felt", "Base": "Natural rubber"},
    },
    {
        "name": "Coiled Aviator Cable", "category": "accessories",
        "spec": "USB-C · Braided · 1.5 m",
        "price": 35, "is_new": True, "rating": 4.7, "review_count": 54,
        "gallery": ["1760377821967-8bb2f250e041", "1756576357688-c637013d3483", "1607125516845-fa8a14db083a"],
        "swatches": [("Black", "#1d1d1f"), ("Red", "#c8312b")],
        "stock": [15, 9],
        "summary": "A braided, coiled USB-C cable with a detachable aviator connector. Tidy on the desk, easy to unplug.",
        "highlights": ["Detachable 5-pin aviator connector", "Double-sleeved paracord braid", "Supports 2.4 GHz dongle passthrough"],
        "specs": {"Length": "1.5 m (incl. coil)", "Connectors": "USB-C to USB-A", "Sleeve": "Paracord + techflex", "Data": "USB 2.0"},
    },
    {
        "name": "Walnut Wrist Rest", "category": "accessories",
        "spec": "Solid walnut · Fits 65–75%",
        "price": 45, "compare_at": 55, "rating": 4.8, "review_count": 101,
        "gallery": ["1627509493009-9249a2ad2459"],
        "stock": [8],
        "summary": "A solid walnut wrist rest, hand-finished with oil, that keeps your wrists level with the keys.",
        "highlights": ["Solid American walnut", "Hand-finished with natural oil", "Rubber feet keep it in place"],
        "specs": {"Material": "American walnut", "Size": "330 × 85 × 18 mm", "Fits": "65% and 75% keyboards", "Feet": "Silicone"},
    },
]

# Products 5–8 are the newest, so they fill "New arrivals" in their listed order.
NEW_ARRIVALS_FROM = 4

PRODUCT_DEFAULTS = {
    "layout": None, "compare_at": None, "is_new": False, "is_preorder": False, "preorder_ships": None,
}
PRODUCT_FIELDS = (
    "name", "layout", "spec", "summary", "price", "compare_at", "is_new", "rating", "review_count",
    "is_preorder", "preorder_ships", "gallery", "highlights", "specs",
)


def slugify(value):
    return value.lower().replace(" ", "-")


def seed():
    categories = {}
    for position, (slug, name) in enumerate(CATEGORIES):
        category = db.session.scalar(select(Category).where(Category.slug == slug)) or Category(slug=slug)
        category.name, category.position = name, position
        db.session.add(category)
        categories[slug] = category

    now = datetime.now(timezone.utc)
    for index, data in enumerate(PRODUCTS):
        slug = slugify(data["name"])
        product = db.session.scalar(select(Product).where(Product.slug == slug)) or Product(slug=slug)
        for field in PRODUCT_FIELDS:
            setattr(product, field, data[field] if field in data else PRODUCT_DEFAULTS[field])
        product.category = categories[data["category"]]
        age = index - NEW_ARRIVALS_FROM if index >= NEW_ARRIVALS_FROM else len(PRODUCTS) + index
        product.created_at = now - timedelta(days=age)
        _seed_variants(product, data)
        db.session.add(product)

    db.session.commit()


def _seed_variants(product, data):
    existing = {v.sku: v for v in product.variants}
    # No swatches / switches = no such option (NULL on the variant), e.g. a switch pack has one variant.
    colors = data.get("swatches") or [(None, None)]
    combos = [(color, switch) for color in colors for switch in data.get("switches") or [None]]
    keep = []
    for position, (((color, hex_), switch), qty) in enumerate(zip(combos, data["stock"], strict=True)):
        sku = "-".join(part for part in (product.slug, color, switch) if part).upper().replace(" ", "-")
        variant = existing.get(sku) or ProductVariant(sku=sku)
        variant.position, variant.color_name, variant.color_hex, variant.switch_type = position, color, hex_, switch
        variant.price = data.get("variant_prices", {}).get(switch)
        variant.stock_qty = qty
        keep.append(variant)
    product.variants = keep  # delete-orphan removes variants no longer in the seed


def register(app):
    @app.cli.command("seed")
    def seed_command():
        """Load the sample catalog (idempotent)."""
        seed()
        click.echo(f"Seeded {len(CATEGORIES)} categories and {len(PRODUCTS)} products.")
