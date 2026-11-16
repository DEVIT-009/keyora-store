from flask import Blueprint

bp = Blueprint("cart", __name__, url_prefix="/cart")


@bp.app_context_processor
def inject_cart_count():
    # Read from the session only, so the header badge never costs a query.
    return {"cart_count": store.count()}


from app.cart import routes, store  # noqa: E402,F401
