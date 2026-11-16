"""Sign-in for Flask (Flask-Login + server-side session rows, see app/auth/service.py).

Routes and templates use `current_user`, `login_required` and `require_admin` from here.
Flask-Login keeps only a `UserSession` id in the signed session / remember cookie; the user
loader looks that row up on every request, so ended sessions, blocks and role changes
apply at once.
"""

from functools import wraps

from flask import abort, flash, redirect, request, session, url_for
from flask_login import AnonymousUserMixin, LoginManager, current_user, login_user, logout_user  # noqa: F401

from app.auth import service

# Better Auth's tables, left in place by the migration that replaced it (their data was copied
# into `users`). Hidden from Alembic autogenerate until they're dropped by hand.
LEGACY_TABLES = {"user", "session", "account", "verification"}

login_manager = LoginManager()


class AnonymousUser(AnonymousUserMixin):
    is_admin = False
    id = None


login_manager.anonymous_user = AnonymousUser


@login_manager.user_loader
def load_user(session_id):
    user, problem = service.load_session(session_id)
    if user is None:
        # Forget the dead session here: calling logout_user() would ask this loader again.
        session.pop("_user_id", None)
        session.pop("_fresh", None)
        session["_remember"] = "clear"  # Flask-Login deletes the remember cookie on the response
        if request.endpoint != "static":
            flash("This account has been blocked. Contact Keyora support if you think this is a mistake."
                  if problem == "blocked" else "You've been signed out. Please sign in again.", "info")
    return user


def sign_in(user, remember=False):
    service.start_session(user, remember)
    login_user(user, remember=remember)


def sign_out():
    if current_user.is_authenticated:
        service.end_session(current_user.session_id)
    logout_user()


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
    (so the admin area doesn't reveal that it exists). The user row is loaded on every request,
    so removing admin access applies at once."""
    if not current_user.is_authenticated:
        flash("Sign in to continue.", "info")
        return redirect(url_for("account.login", next=request.full_path.rstrip("?")))
    if not current_user.is_admin:
        abort(404)
    return None


def alembic_include_object(obj, name, type_, reflected, compare_to):
    """Keep Alembic autogenerate away from the leftover Better Auth tables."""
    if type_ == "table":
        return name not in LEGACY_TABLES
    return True


def init_app(app):
    login_manager.init_app(app)
    from app.auth import commands
    commands.register(app)
