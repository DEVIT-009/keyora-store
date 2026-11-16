"""Editorial storefront content (hero, perks, banners…). Products live in the database; see app/catalog.py.

Image values are Unsplash photo IDs, rendered through the `img_url` / `img_srcset`
template globals (see app/images.py).
"""

HERO = {
    "eyebrow": "New · Aster series",
    "title": "Every keystroke, considered.",
    "body": "Gasket-mounted aluminum boards with hot-swap sockets and tuned acoustics. Built to be typed on for a decade.",
    "image": "1638909067462-1310c4011610",
}

PERKS = [
    {"icon": "truck", "title": "Free shipping", "body": "On orders over $99"},
    {"icon": "shield", "title": "2-year warranty", "body": "On every keyboard"},
    {"icon": "swap", "title": "Hot-swappable", "body": "Change switches, no solder"},
    {"icon": "return", "title": "30-day returns", "body": "No questions asked"},
]

LAYOUTS = [
    {"name": "Full size", "size": "100%", "count": 6, "image": "1635987391914-cb84b567e68f"},
    {"name": "Tenkeyless", "size": "80%", "count": 9, "image": "1626958390943-a70309376444"},
    {"name": "Compact", "size": "75%", "count": 14, "image": "1632079003110-d694908500da"},
    {"name": "Sixty-five", "size": "65%", "count": 11, "image": "1589578228447-e1a4e481c6c8"},
    {"name": "Sixty", "size": "60%", "count": 7, "image": "1697022976749-35bac4eb77dc"},
]

SWITCH_FEATURE = {
    "eyebrow": "Switch lab",
    "title": "Find the feel that's yours.",
    "body": "Linear, tactile or clicky. Every Keyora board is hot-swappable, so trying a new switch takes a minute and a puller, not a soldering iron.",
    "points": [
        ("Factory-lubed", "Smooth from the first press"),
        ("5-pin sockets", "Fits nearly every MX-style switch"),
        ("Sampler packs", "Try 12 switches before you commit"),
    ],
    "image": "1595044426077-d36d9236d54a",
}

COLLECTIONS = [
    {"name": "Keycaps", "slug": "keycaps", "body": "Double-shot PBT in 40+ colorways", "image": "1612538811009-ed19118a2b53"},
    {"name": "Switches", "slug": "switches", "body": "Linear, tactile & clicky", "image": "1777259113729-9bda92fb8ce8"},
    {"name": "Desk accessories", "slug": "accessories", "body": "Wrist rests, cables & mats", "image": "1627509493009-9249a2ad2459"},
]

# Category art and copy, keyed by Category.slug. A category without an entry falls back to DEFAULT_CATEGORY_ART.
CATEGORY_ART = {
    "keyboards": {"body": "Gasket-mounted, hot-swap boards from 60% to full size", "image": "1618384887929-16ec33fab9ef"},
    "switches": {"body": "Linear, tactile & clicky, factory-lubed", "image": "1777259113729-9bda92fb8ce8"},
    "keycaps": {"body": "Double-shot PBT in 40+ colorways", "image": "1612538811009-ed19118a2b53"},
    "accessories": {"body": "Wrist rests, coiled cables & desk mats", "image": "1627509493009-9249a2ad2459"},
}
DEFAULT_CATEGORY_ART = {"body": "", "image": "1595044426077-d36d9236d54a"}


def category_art(slug):
    return CATEGORY_ART.get(slug, DEFAULT_CATEGORY_ART)


SETUP_BANNER = {
    "eyebrow": "Setups",
    "title": "Designed for the desk you actually work at.",
    "body": "Low-profile, wireless and quiet enough for a shared office. Browse setups from our community.",
    "image": "1741277421579-382768cd62e8",
}

REVIEWS = [
    {"quote": "The typing sound is unreal — deep and muted without any mods. Battery lasts weeks.", "name": "Priya S.", "product": "Aster 75 Wireless"},
    {"quote": "Swapped in tactile switches in five minutes. Build quality feels far above the price.", "name": "Marcus L.", "product": "Aster 65 Aluminum"},
    {"quote": "Finally a 60% that doesn't feel cheap. Heavy, solid and the keycaps are thick PBT.", "name": "Jonas K.", "product": "Mono 60"},
]
