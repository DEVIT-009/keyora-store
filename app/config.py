import os

from dotenv import load_dotenv

load_dotenv()


def database_url():
    """DATABASE_URL as given by Neon/Heroku etc., pointed at the psycopg 3 driver."""
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://localhost/keyora")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-secret")
    # Every POST form carries a CSRF token (Flask-WTF); Lax cookies are a second layer.
    SESSION_COOKIE_SAMESITE = "Lax"
    # Tie CSRF tokens to the session instead of expiring after an hour, so a cart or
    # checkout tab left open doesn't fail on submit.
    WTF_CSRF_TIME_LIMIT = None
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Neon suspends idle databases and closes their connections; check before reuse.
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    SQLALCHEMY_ECHO = os.environ.get("SQLALCHEMY_ECHO") == "1"

    # Better Auth (auth-server/). BETTER_AUTH_URL is the public origin of this Flask app:
    # cookies are issued for it and it's sent as Origin on server-to-server calls.
    BETTER_AUTH_URL = os.environ.get("BETTER_AUTH_URL", "http://127.0.0.1:5000")
    AUTH_SERVER_URL = os.environ.get("AUTH_SERVER_URL", "http://127.0.0.1:3005")
    AUTH_TIMEOUT = float(os.environ.get("AUTH_TIMEOUT", "5"))

    # Bakong KHQR (app/checkout/khqr.py, bakong.py). The token is a server secret: never
    # render or log it. Merchant fields go into the QR and must be ASCII; empty = unset.
    BAKONG_API_URL = os.environ.get("BAKONG_API_URL") or "https://api-bakong.nbc.gov.kh/v1"
    BAKONG_TOKEN = os.environ.get("BAKONG_TOKEN", "")
    BAKONG_ACCOUNT_ID = os.environ.get("BAKONG_ACCOUNT_ID", "")
    BAKONG_TIMEOUT = float(os.environ.get("BAKONG_TIMEOUT") or 12)
    MERCHANT_NAME = os.environ.get("MERCHANT_NAME") or "Keyora"  # ≤ 25
    MERCHANT_CITY = os.environ.get("MERCHANT_CITY") or "Phnom Penh"  # ≤ 15
    MERCHANT_PHONE = os.environ.get("MERCHANT_PHONE") or None  # optional, tag 62/02
    STORE_LABEL = os.environ.get("STORE_LABEL") or None  # optional, ≤ 25, tag 62/03
    TERMINAL_LABEL = os.environ.get("TERMINAL_LABEL") or None  # optional, ≤ 25, tag 62/07
    KHQR_CURRENCY = "USD"  # catalog prices are dollars
    # Minutes a checkout QR stays payable; stock is held for the same time.
    KHQR_EXPIRATION_MINUTES = int(os.environ.get("KHQR_EXPIRATION_MINUTES") or 15)

    # Cloudinary product photo uploads (app/cloudinary.py). The secret is server-only; all
    # three unset = the admin upload field is hidden and Unsplash ids still work.
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")
    CLOUDINARY_FOLDER = os.environ.get("CLOUDINARY_FOLDER") or "keyora/products"
    CLOUDINARY_TIMEOUT = float(os.environ.get("CLOUDINARY_TIMEOUT") or 30)
    # Whole request cap (up to 10 photos × 10 MB plus the form); larger posts get a 413.
    MAX_CONTENT_LENGTH = 105 * 1024 * 1024
