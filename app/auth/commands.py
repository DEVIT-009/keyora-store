"""Account CLI: `flask seed-users`, `flask set-role`, `flask set-password`."""

import os
import secrets

import click

from app.auth import service
from app.extensions import db
from app.models import ROLES

SEED_ACCOUNTS = (
    ("Keyora Admin", "admin@keyora.test", "admin", "SEED_ADMIN_PASSWORD"),
    ("Sok Dara", "customer@keyora.test", "user", "SEED_USER_PASSWORD"),
)


def register(app):
    @app.cli.command("seed-users")
    def seed_users():
        """One admin + one customer. Idempotent: existing accounts only get their role fixed.

        Passwords come from SEED_ADMIN_PASSWORD / SEED_USER_PASSWORD, else a random one is
        printed once for each new account.
        """
        for name, email, role, password_env in SEED_ACCOUNTS:
            user = service.get_by_email(email)
            if user is None:
                password = os.environ.get(password_env) or secrets.token_urlsafe(12)
                user = service.register(name, email, password)
                shown = f"(from {password_env})" if os.environ.get(password_env) else password
                state = "created"
            else:
                shown, state = "(unchanged)", "exists "
            user.role = role
            db.session.commit()
            click.echo(f"{state}  {role:<5}  {email}  password: {shown}")

    @app.cli.command("set-role")
    @click.argument("email")
    @click.argument("role", type=click.Choice(ROLES))
    def set_role(email, role):
        """Make an account an admin (or a normal user again)."""
        user = service.get_by_email(email) or _missing(email)
        user.role = role
        db.session.commit()
        click.echo(f"{user.email} is now {role}.")

    @app.cli.command("set-password")
    @click.argument("email")
    @click.password_option()
    def set_password(email, password):
        """Reset an account's password and sign it out everywhere."""
        if not 8 <= len(password) <= 128:
            raise click.ClickException("Use 8 to 128 characters.")
        user = service.get_by_email(email) or _missing(email)
        service.set_password(user, password)
        click.echo(f"Password changed for {user.email}; all its sessions were ended.")


def _missing(email):
    raise click.ClickException(f"No account with email {email}.")
