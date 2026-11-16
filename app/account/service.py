"""Saved-address queries and writes, keyed by the Better Auth user id (a string).

Accounts themselves (sign-up, sign-in, profile, password) go through app/auth/client.py.
Every lookup is scoped to the user so ids from the URL can't reach someone else's rows.
"""

from sqlalchemy import select, update

from app.extensions import db
from app.models import Address


def list_addresses(user_id):
    """Default first, then oldest first."""
    return db.session.scalars(
        select(Address).where(Address.user_id == user_id).order_by(Address.is_default.desc(), Address.id)
    ).all()


def get_address(user_id, address_id):
    return db.session.scalar(select(Address).where(Address.id == address_id, Address.user_id == user_id))


def save_address(user_id, data, address=None):
    """Create or update. The user's only address is always the default."""
    if address is None:
        address = Address(user_id=user_id)
        db.session.add(address)
    for field in ("receiver_name", "phone", "province", "address"):
        setattr(address, field, data[field])
    others = [a for a in list_addresses(user_id) if a is not address]
    make_default = data["is_default"] or not any(a.is_default for a in others)
    if make_default:
        _clear_default(user_id, keep=address)
    address.is_default = make_default
    db.session.commit()
    return address


def set_default_address(user_id, address):
    _clear_default(user_id, keep=address)
    address.is_default = True
    db.session.commit()


def delete_address(user_id, address):
    """Delete; if it was the default, the oldest remaining address takes over."""
    was_default = address.is_default
    db.session.delete(address)
    db.session.flush()
    if was_default and (remaining := list_addresses(user_id)):
        remaining[0].is_default = True
    db.session.commit()


def _clear_default(user_id, keep):
    # Flushed before the new default is set, so the one-default-per-user index never sees two.
    db.session.execute(
        update(Address)
        .where(Address.user_id == user_id, Address.is_default, Address.id != (keep.id or 0))
        .values(is_default=False)
    )
    db.session.flush()
