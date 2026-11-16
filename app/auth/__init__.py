"""Better Auth session handling for Flask.

Flask never validates Better Auth cookies itself: on each request that carries them it
asks the auth service (`GET /get-session`) and exposes the result as `current_user`.
"""

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from functools import wraps

from flask import abort, flash, g, redirect, request, url_for
from sqlalchemy import text
from werkzeug.local import LocalProxy

from app.auth import client
from app.auth.client import AuthUnavailable  # noqa: F401  (re-exported for routes)
from app.extensions import db

log = logging.getLogger(__name__)

# Tables created and migrated by Better Auth (`npm --prefix auth-server run migrate`).
BETTER_AUTH_TABLES = {"user", "session", "account", "verification"}

# Cookie names Better Auth may set; cleared locally if sign-out can't reach the service.
_AUTH_COOKIES = ("session_token", "session_data", "dont_remember")


class AnonymousUser:
    is_authenticated = False
    is_admin = False
    id = None


ANONYMOUS = AnonymousUser()


@dataclass(frozen=True)
class SessionUser:
    id: str
    name: str
    email: str
    phone: str | None
    created_at: datetime
    role: str = "user"
    is_authenticated: bool = True

    @classmethod
    def from_json(cls, user):
        return cls(
            id=user["id"],
            name=user.get("name") or "",
            email=user["email"],
            phone=user.get("phone") or None,
            created_at=datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00")),
            role=user.get("role") or "user",
        )

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def full_name(self):
        return self.name

    @property
    def first_name(self):
        return self.name.split()[0] if self.name.strip() else ""


current_user = LocalProxy(lambda: g.get("user", ANONYMOUS))


# The session row must still exist (admins can revoke it) and the user must not be blocked.
# Also returns the current role: the session's copy can be up to 5 minutes old.
_SESSION_CHECK = text("""
    SELECT u.role, (u.banned IS TRUE AND (u."banExpires" IS NULL OR u."banExpires" > now())) AS blocked
    FROM "session" s JOIN "user" u ON u.id = s."userId"
    WHERE s.id = :session_id AND s."userId" = :user_id AND s."expiresAt" > now()
""")


def load_current_user():
    g.user = ANONYMOUS
    if request.endpoint == "static" or not client.has_auth_cookie():
        return
    try:
        result = client.get_session()
    except AuthUnavailable as exc:
        log.warning("Auth service unavailable, treating request as signed out: %s", exc)
        return
    if not (result.ok and isinstance(result.data, dict) and result.data.get("user")):
        return
    user = SessionUser.from_json(result.data["user"])
    # get-session may answer from Better Auth's signed cookie cache (auth-server/auth.ts) without
    # looking at the DB, so a session an admin revoked, or a user they blocked, would keep working
    # for up to 5 minutes. One indexed lookup per signed-in request makes both take effect at once.
    row = db.session.execute(
        _SESSION_CHECK, {"session_id": (result.data.get("session") or {}).get("id"), "user_id": user.id}
    ).one_or_none()
    if row is None or row.blocked:
        g.end_auth = True  # relay_cookies clears the browser's auth cookies
        flash("This account has been blocked. Contact Keyora support if you think this is a mistake."
              if row is not None else "You've been signed out. Please sign in again.", "info")
        return
    g.user = replace(user, role=row.role or "user")


def relay_cookies(response):
    """Copy Better Auth's Set-Cookie headers (sign-in, refresh, sign-out) onto our response,
    or clear the auth cookies when this request found the session revoked / the user blocked."""
    cookies = g.pop("auth_set_cookies", [])
    if g.pop("end_auth", False):
        return clear_auth_cookies(response)
    for cookie in cookies:
        response.headers.add("Set-Cookie", cookie)
    return response


def clear_auth_cookies(response):
    """Expire the auth cookies locally (sign-out while the auth service is down, revoked sessions)."""
    for prefix in client.COOKIE_PREFIXES:
        for name in _AUTH_COOKIES:
            if prefix + name in request.cookies:
                response.delete_cookie(prefix + name, path="/")
    return response


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Sign in to see your account.", "info")
            return redirect(url_for("account.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def require_admin():
    """For `bp.before_request`: sign-in redirect for guests, 404 for signed-in non-admins
    (so the admin area doesn't reveal that it exists). `current_user.role` is read from the DB
    on every request (load_current_user), so removing admin access applies at once."""
    if not current_user.is_authenticated:
        flash("Sign in to continue.", "info")
        return redirect(url_for("account.login", next=request.full_path.rstrip("?")))
    if not current_user.is_admin:
        abort(404)
    return None


def alembic_include_object(obj, name, type_, reflected, compare_to):
    """Keep Alembic autogenerate away from Better Auth's tables, and from our hand-written
    FKs into them (e.g. addresses.user_id -> "user".id), which the models can't declare."""
    if type_ == "table":
        return name not in BETTER_AUTH_TABLES
    if type_ == "foreign_key_constraint":
        return obj.referred_table.name not in BETTER_AUTH_TABLES
    return True


def init_app(app):
    app.before_request(load_current_user)
    app.after_request(relay_cookies)
    app.context_processor(lambda: {"current_user": current_user})
