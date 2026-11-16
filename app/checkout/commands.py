"""`flask expire-orders` (optional cron, DB only) and `flask bakong-check` (setup sanity check)."""

import click
from flask import current_app

from app.checkout import bakong, khqr, orders
from app.checkout.bakong import BakongUnavailable


def register(app):
    @app.cli.command("expire-orders")
    def expire_orders():
        """Expire overdue pending orders and release their stock. Never calls Bakong."""
        click.echo(f"Expired {orders.expire_overdue()} orders.")

    @app.cli.command("bakong-check")
    def bakong_check():
        """Encoder self-test plus a live check of the token and BAKONG_ACCOUNT_ID."""
        ok = khqr.selftest()
        click.echo(f"KHQR encoder self-test (CRC 58D8): {'ok' if ok else 'FAILED'}")
        config = current_app.config
        account = config["BAKONG_ACCOUNT_ID"]
        try:
            exists = bakong.check_account(account)
        except BakongUnavailable as exc:
            raise click.ClickException(f"Bakong API unavailable: {exc} (401 = token, 403 = non-Cambodian IP)")
        click.echo(f"Bakong account {account}: {'found' if exists else 'NOT FOUND'}")
        if not ok or not exists:
            raise SystemExit(1)
