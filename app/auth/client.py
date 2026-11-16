"""Server-to-server client for the Better Auth service in auth-server/.

Flask is the only caller. Each call forwards the browser's Better Auth cookies, its IP
and User-Agent (so Better Auth's per-IP rate limiting and session records see the real
client, not 127.0.0.1), and sends Origin = BETTER_AUTH_URL so Better Auth's origin
check passes. Set-Cookie headers from Better Auth are queued on `g` and copied onto
the Flask response by `relay_cookies` (see app/auth/__init__.py).
"""

from dataclasses import dataclass, field

import requests
from flask import current_app, g, request

COOKIE_PREFIXES = ("better-auth.", "__Secure-better-auth.")


class AuthUnavailable(Exception):
    """The auth service couldn't be reached or answered with a server error."""


@dataclass
class AuthResult:
    status: int
    data: object = None
    error: str | None = None  # Better Auth error code, e.g. "INVALID_EMAIL_OR_PASSWORD"
    set_cookies: list[str] = field(default_factory=list)

    @property
    def ok(self):
        return self.error is None


def auth_cookie_header():
    """Only the browser's Better Auth cookies, raw — Flask's own session cookie never leaves."""
    pairs = [p.strip() for p in request.headers.get("Cookie", "").split(";")]
    return "; ".join(p for p in pairs if p.split("=", 1)[0].startswith(COOKIE_PREFIXES))


def has_auth_cookie():
    return bool(auth_cookie_header())


def _call(method, path, payload=None):
    headers = {
        "Origin": current_app.config["BETTER_AUTH_URL"],
        "User-Agent": request.user_agent.string or "keyora-flask",
        "X-Forwarded-For": request.remote_addr or "",
    }
    if cookies := auth_cookie_header():
        headers["Cookie"] = cookies
    try:
        response = requests.request(
            method,
            current_app.config["AUTH_SERVER_URL"].rstrip("/") + "/api/auth" + path,
            json=payload,
            headers=headers,
            timeout=current_app.config["AUTH_TIMEOUT"],
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise AuthUnavailable(str(exc)) from exc
    if response.status_code >= 500:
        raise AuthUnavailable(f"{path} returned {response.status_code}")

    try:
        data = response.json() if response.content else None
    except ValueError:
        data = None
    error = None
    if not response.ok:
        error = (data.get("code") if isinstance(data, dict) else None) or f"HTTP_{response.status_code}"

    set_cookies = response.raw.headers.getlist("Set-Cookie")
    g.setdefault("auth_set_cookies", []).extend(set_cookies)
    return AuthResult(response.status_code, data, error, set_cookies)


def get_session():
    return _call("GET", "/get-session")


def sign_up(name, email, password):
    return _call("POST", "/sign-up/email", {"name": name, "email": email, "password": password})


def sign_in(email, password, remember):
    return _call("POST", "/sign-in/email", {"email": email, "password": password, "rememberMe": remember})


def sign_out():
    return _call("POST", "/sign-out", {})


def update_user(name, phone):
    return _call("POST", "/update-user", {"name": name, "phone": phone or None})


def change_password(current_password, new_password):
    return _call("POST", "/change-password", {
        "currentPassword": current_password,
        "newPassword": new_password,
        "revokeOtherSessions": True,
    })
