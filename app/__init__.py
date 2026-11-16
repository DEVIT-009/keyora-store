from decimal import Decimal

from flask import Flask, render_template
from flask_wtf.csrf import CSRFError

from app.config import Config
from app import auth
from app.extensions import csrf, db, migrate
from app.images import img_srcset, img_url


def money(value):
    """$169 for whole amounts, $169.50 otherwise."""
    value = Decimal(value)
    return f"${value:,.0f}" if value == value.to_integral_value() else f"${value:,.2f}"


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db, include_object=auth.alembic_include_object)
    csrf.init_app(app)
    auth.init_app(app)

    from app import models  # noqa: F401  (registers tables for Flask-Migrate)
    from app import seed
    seed.register(app)

    app.jinja_env.globals.update(img_url=img_url, img_srcset=img_srcset)
    app.jinja_env.filters["money"] = money

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.cart import bp as cart_bp
    app.register_blueprint(cart_bp)

    from app.checkout import bp as checkout_bp
    app.register_blueprint(checkout_bp)
    from app.checkout import commands as checkout_commands
    checkout_commands.register(app)

    from app.account import bp as account_bp
    app.register_blueprint(account_bp)

    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        return render_template("csrf_error.html"), 400

    return app
