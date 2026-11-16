"""Product photo uploads to Cloudinary (admin only). Server-side, signed, no SDK.

Every upload is decoded with Pillow and re-encoded as WebP before it leaves the server, so
Cloudinary only ever stores .webp: the real format is checked (not just the extension),
EXIF/GPS is dropped, phone photos are turned upright and huge photos are scaled down.
Gallery entries for uploads are stored as `cld:<public_id>`; app/images.py builds their URLs.
Unsplash ids keep working side by side. The API secret is never logged or rendered.
"""

import hashlib
import io
import logging
import time

import requests
from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

log = logging.getLogger(__name__)

PREFIX = "cld:"
EXTENSIONS = (".jpeg", ".jpg", ".png", ".webp")
FORMATS = {"JPEG", "PNG", "WEBP"}  # what Pillow must actually find inside the file
ACCEPT = ".jpeg,.jpg,.png,.webp,image/jpeg,image/png,image/webp"
MAX_BYTES = 10 * 1024 * 1024  # per file, as uploaded
MAX_FILES = 10  # per save
MAX_PIXELS = 40_000_000  # refuse decompression bombs before decoding
MAX_SIDE = 2400  # longest side stored; the storefront asks for at most 1600 px
WEBP_QUALITY = 85


class BadImage(ValueError):
    """The file isn't an image we accept; the message is shown to staff."""


class CloudinaryUnavailable(Exception):
    """Cloudinary isn't configured or didn't accept the upload."""


def configured():
    config = current_app.config
    return all(config[k] for k in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"))


def to_webp(file):
    """WebP bytes for an uploaded werkzeug FileStorage, or BadImage."""
    name = file.filename or "photo"
    if not name.lower().endswith(EXTENSIONS):
        raise BadImage(f"{name}: use a .jpg, .jpeg, .png or .webp file.")
    raw = file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise BadImage(f"{name}: keep each photo under {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        image = Image.open(io.BytesIO(raw))  # reads the header only
        if image.format not in FORMATS:
            raise BadImage(f"{name}: this isn't a JPEG, PNG or WebP image.")
        if image.width * image.height > MAX_PIXELS:
            raise BadImage(f"{name}: this photo is too large ({image.width}×{image.height}).")
        image.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG: decode at reduced size when possible
        image = ImageOps.exif_transpose(image)  # also loads the pixels
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise BadImage(f"{name}: this file couldn't be read as an image.") from exc
    if image.mode not in ("RGB", "RGBA"):
        has_alpha = image.mode in ("LA", "PA") or "transparency" in image.info
        image = image.convert("RGBA" if has_alpha else "RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "WEBP", quality=WEBP_QUALITY, method=4)  # no exif= → metadata dropped
    return out.getvalue()


def upload(webp):
    """Upload WebP bytes; returns the gallery entry (`cld:<public_id>`)."""
    if not configured():
        raise CloudinaryUnavailable("CLOUDINARY_* is not set")
    config = current_app.config
    params = {"folder": config["CLOUDINARY_FOLDER"], "timestamp": str(int(time.time()))}
    to_sign = "&".join(f"{k}={v}" for k, v in sorted(params.items())) + config["CLOUDINARY_API_SECRET"]
    try:
        response = requests.post(
            f"https://api.cloudinary.com/v1_1/{config['CLOUDINARY_CLOUD_NAME']}/image/upload",
            data={**params, "api_key": config["CLOUDINARY_API_KEY"],
                  "signature": hashlib.sha1(to_sign.encode()).hexdigest()},
            files={"file": ("photo.webp", webp, "image/webp")},
            timeout=config["CLOUDINARY_TIMEOUT"],
        )
    except requests.RequestException as exc:
        log.warning("Cloudinary upload failed: %s", type(exc).__name__)
        raise CloudinaryUnavailable(type(exc).__name__) from exc
    if not response.ok:
        # 401 = wrong key/secret, 400 = rejected file or stale timestamp, 420 = rate limited.
        log.warning("Cloudinary upload returned HTTP %s", response.status_code)
        raise CloudinaryUnavailable(f"HTTP {response.status_code}")
    try:
        public_id = response.json()["public_id"]
    except (ValueError, KeyError) as exc:
        raise CloudinaryUnavailable("unexpected response") from exc
    return PREFIX + public_id
