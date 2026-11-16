"""Accounts: password hashing, sign-up / sign-in, server-side sessions, lockouts.

- Passwords are hashed with Werkzeug's scrypt. Accounts migrated from Better Auth keep their
  old hash (`better-auth:<salt>:<key>`, Node scrypt N=16384 r=16 p=1, 64-byte key, the hex
  salt string itself as the salt); it's verified here and replaced with a Werkzeug hash at
  the first successful sign-in.
- Every sign-in creates a `UserSession` row; Flask-Login stores only that row's id (see
  `User.get_id`). Deleting rows is how sign-out, password changes, admin blocks and
  "sign out everywhere" take effect on the other browsers' next request.
- Repeated wrong passwords lock that email for a few minutes (`LoginThrottle`), tracked
  whether or not the account exists, so the lockout doesn't reveal which emails have one.
"""

import hashlib
import hmac
import unicodedata
from datetime import datetime, timedelta, timezone

from flask import request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import LoginThrottle, User, UserSession

SESSION_DAYS = 1  # "Keep me signed in" unticked: the server session ends after a day
REMEMBER_DAYS = 30
TOUCH_EVERY = timedelta(minutes=5)  # how stale `last_active` may get before it's rewritten
MAX_FAILURES = 5  # wrong passwords within FAILURE_WINDOW before the email is locked
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=5)

_LEGACY_PREFIX = "better-auth:"
# Compared against when the email has no account, so both paths take about as long.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


class EmailTaken(Exception):
    pass


class TooManyAttempts(Exception):
    pass


class Blocked(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _normalize(password):
    return unicodedata.normalize("NFKC", password)


def normalize_email(email):
    return email.strip().lower()


def hash_password(password):
    return generate_password_hash(_normalize(password))


def _check_legacy(stored, password):
    salt, _, key = stored.removeprefix(_LEGACY_PREFIX).partition(":")
    if not salt or not key:
        return False
    derived = hashlib.scrypt(_normalize(password).encode(), salt=salt.encode(), n=16384, r=16, p=1,
                             dklen=64, maxmem=64 * 1024 * 1024)
    return hmac.compare_digest(derived.hex(), key)


def check_password(user, password):
    """True if `password` is right. Upgrades a Better Auth hash in place (caller commits)."""
    stored = user.password_hash or ""
    if stored.startswith(_LEGACY_PREFIX):
        if not _check_legacy(stored, password):
            return False
        user.password_hash = hash_password(password)
        return True
    if not stored.startswith(("scrypt:", "pbkdf2:")):  # "!" = no usable password
        return False
    return check_password_hash(stored, _normalize(password))


def get_by_email(email):
    return db.session.scalar(select(User).where(User.email == normalize_email(email)))


# ---------- Sign-up / sign-in ----------

def register(name, email, password, phone=None):
    user = User(name=name, email=normalize_email(email), phone=phone or None,
                password_hash=hash_password(password))
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise EmailTaken from None
    return user


def authenticate(email, password):
    """The user for a correct email + password. Raises TooManyAttempts while the email is locked
    and Blocked for a blocked account (only after the password checked out, so a block isn't
    revealed to someone guessing). Returns None for a wrong email or password."""
    email = normalize_email(email)
    throttle = db.session.get(LoginThrottle, email)
    if throttle and throttle.locked_until and throttle.locked_until > _now():
        raise TooManyAttempts
    user = get_by_email(email)
    if user is None:
        check_password_hash(_DUMMY_HASH, password)
        ok = False
    else:
        ok = check_password(user, password)
    if not ok:
        _record_failure(email, throttle)
        return None
    if throttle:
        db.session.delete(throttle)
    db.session.commit()  # also saves an upgraded password hash
    if user.is_blocked:
        raise Blocked
    return user


def _record_failure(email, throttle):
    now = _now()
    if throttle is None:
        throttle = LoginThrottle(email=email, failures=0, first_failed_at=now)
        db.session.add(throttle)
    elif now - throttle.first_failed_at > FAILURE_WINDOW:
        throttle.failures, throttle.first_failed_at, throttle.locked_until = 0, now, None
    throttle.failures += 1
    if throttle.failures >= MAX_FAILURES:
        throttle.failures, throttle.first_failed_at, throttle.locked_until = 0, now, now + LOCKOUT
    try:
        db.session.commit()
    except IntegrityError:  # two failures for a new email at once; one counter is enough
        db.session.rollback()


# ---------- Sessions ----------

def start_session(user, remember=False):
    """Create the server-side session row and attach its id to `user` for Flask-Login."""
    session_row = UserSession(
        user_id=user.id,
        expires_at=_now() + timedelta(days=REMEMBER_DAYS if remember else SESSION_DAYS),
        ip_address=(request.remote_addr or "")[:64] or None,
        user_agent=request.headers.get("User-Agent", "")[:500] or None,
    )
    db.session.add(session_row)
    db.session.commit()
    user.session_id = session_row.id
    return session_row


def load_session(session_id):
    """(user, problem) for a session id from the Flask session / remember cookie.
    problem is None when signed in, else "ended" (row gone or expired) or "blocked"."""
    if not session_id:
        return None, "ended"
    row = db.session.scalar(
        select(UserSession).where(UserSession.id == session_id, UserSession.expires_at > _now())
    )
    if row is None:
        return None, "ended"
    user = row.user
    if user.is_blocked:
        end_all_sessions(user.id)
        db.session.commit()
        return None, "blocked"
    if _now() - row.last_active > TOUCH_EVERY:
        row.last_active = _now()
        db.session.commit()
    user.session_id = row.id
    return user, None


def end_session(session_id):
    db.session.execute(delete(UserSession).where(UserSession.id == session_id))
    db.session.commit()


def end_all_sessions(user_id, keep=None):
    """Delete the user's sessions (except `keep`); the caller commits. Returns how many ended."""
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if keep:
        stmt = stmt.where(UserSession.id != keep)
    return db.session.execute(stmt).rowcount


# ---------- Profile ----------

def update_profile(user, name, phone):
    user.name, user.phone, user.updated_at = name, phone or None, _now()
    db.session.commit()


def change_password(user, current, new):
    """False if `current` is wrong. Signs out every other browser of this user."""
    if not check_password(user, current):
        db.session.rollback()
        return False
    user.password_hash, user.updated_at = hash_password(new), _now()
    end_all_sessions(user.id, keep=user.session_id)
    db.session.commit()
    return True


def set_password(user, password):
    """For the CLI: new password, every session ended."""
    user.password_hash, user.updated_at = hash_password(password), _now()
    end_all_sessions(user.id)
    db.session.commit()
