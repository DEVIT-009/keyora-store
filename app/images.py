"""Helpers for building responsive image URLs from stored photo ids.

An id is either an Unsplash photo id ("1618384887929-16ec33fab9ef") or a Cloudinary upload
("cld:keyora/products/abc123", see app/cloudinary.py — always stored as WebP).
"""

from flask import current_app

UNSPLASH = "https://images.unsplash.com/photo-{id}?auto=format&fit=crop&q=70&w={w}"
CLOUDINARY = "https://res.cloudinary.com/{cloud}/image/upload/{transform}/{public_id}.webp"


def img_url(photo_id, w, h=None):
    if photo_id.startswith("cld:"):
        transform = f"c_fill,g_auto,w_{w},h_{h},q_auto" if h else f"c_limit,w_{w},q_auto"
        return CLOUDINARY.format(cloud=current_app.config["CLOUDINARY_CLOUD_NAME"], transform=transform,
                                 public_id=photo_id.removeprefix("cld:"))
    url = UNSPLASH.format(id=photo_id, w=w)
    return f"{url}&h={h}" if h else url


def img_srcset(photo_id, widths, ratio=None):
    """`ratio` is height/width; when set, every candidate is cropped to it."""
    return ", ".join(
        f"{img_url(photo_id, w, round(w * ratio) if ratio else None)} {w}w" for w in widths
    )
