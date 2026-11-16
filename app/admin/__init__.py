from flask import Blueprint

from app.auth import require_admin

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Every admin route: guests go to sign-in, non-admins get 404 (role read fresh from the DB).
bp.before_request(require_admin)


@bp.after_request
def _no_store(response):
    """Admin pages show customer data; never cache them (shared or browser)."""
    response.headers["Cache-Control"] = "no-store"
    return response


from app.admin import routes  # noqa: E402,F401
