# Keyora

An e-commerce storefront for mechanical keyboards, built with Flask, Jinja2 and Tailwind CSS, backed by PostgreSQL, with customer accounts handled by [Flask-Login](https://flask-login.readthedocs.io/).

## Features

- **Storefront**: an editorial homepage, product pages with colour × switch variants, live stock states (in stock, low stock, sold out, pre-order) and related products.
- **Cart**: session-based, so no database tables. Prices and stock are always re-read from the catalog, quantities are capped at what's available, and a free-shipping progress bar tracks the $99 threshold.
- **Checkout**: contact → shipping address (Cambodia's 25 provinces) → delivery or pickup → pay with KHQR (confirmed with Bakong), with stock reserved while the QR is valid.
- **Accounts**: register, sign in and out, edit your profile and password, and manage saved addresses with a default, and see your orders and their shipping status.
- **Admin** (`/admin`): orders and fulfilment, products and stock, categories, customers (block, sign out everywhere, roles) and an activity log.
- **Design system**: Tailwind v4 tokens and reusable components. `/styleguide` shows every one of them.
- **Security**: CSRF protection on every form, server-side validation, and safe redirects after sign-in. Address lookups are always limited to the signed-in user.

## Tech stack

| Layer | Tools |
|---|---|
| Web app | Flask 3 (app factory + Blueprints), Jinja2, Flask-WTF (CSRF) |
| Styling | Tailwind CSS v4 via `@tailwindcss/cli` |
| Database | PostgreSQL (Neon or local), Flask-SQLAlchemy (SQLAlchemy 2), psycopg 3, Flask-Migrate / Alembic |
| Auth | Flask-Login, email + password, server-side sessions |
| Images | Unsplash photo IDs, with responsive `srcset` |

## Architecture

One Flask app and one PostgreSQL database; Node is only used to build the CSS.

- Accounts live in our own tables: `users`, `user_sessions` (one row per signed-in browser) and `login_throttle`. Flask-Login keeps only the session row's id in the signed cookie, and every request looks it up, so signing out, changing a password, or an admin blocking someone takes effect on that browser's next request.
- Passwords are hashed with Werkzeug's scrypt. Five wrong passwords for an email lock it for five minutes.
- Accounts made while the project used Better Auth were copied over with the same ids, so their orders and addresses stay linked, and their old passwords still work (they're re-hashed at the next sign-in).

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (or pip)
- Node.js (only for the Tailwind CSS build)
- PostgreSQL 14+, either a [Neon](https://neon.tech) project or a local install

## Getting started

```bash
# 1. Install dependencies
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
npm install                          # Tailwind CLI

# 2. Configure
cp .env.example .env
# then set DATABASE_URL and SECRET_KEY

# 3. Create the database schema
.venv/bin/flask --app run db upgrade       # all tables
.venv/bin/flask --app run seed             # sample catalog (safe to re-run)
.venv/bin/flask --app run seed-users       # optional: one admin + one customer account

# 4. Build CSS
npm run build:css
```

`seed-users` creates `admin@keyora.test` (admin) and `customer@keyora.test` (customer). It prints a random password for each new account once; set `SEED_ADMIN_PASSWORD` / `SEED_USER_PASSWORD` to choose your own. Running it again leaves existing accounts alone. Other account commands: `flask --app run set-role EMAIL admin|user` and `flask --app run set-password EMAIL`.

## Running locally

```bash
.venv/bin/python run.py              # Flask on http://127.0.0.1:5000
npm run watch:css                    # optional: rebuild CSS on change
```

Open **http://127.0.0.1:5000**, not `localhost`: on macOS, AirPlay Receiver also listens on port 5000 and answers `localhost` with 403.

| URL | Page |
|---|---|
| `/` | Homepage |
| `/categories` | All categories |
| `/categories/<slug>` | Category listing, with layout filter (e.g. `/categories/keyboards?layout=75%25`) |
| `/search?q=` | Search (newest products when empty) |
| `/products/<slug>` | Product page (e.g. `/products/aster-75-wireless`) |
| `/cart` | Cart |
| `/checkout` | Checkout (preview) |
| `/account` | Account (sign in at `/account/login`, register at `/account/register`) |
| `/styleguide` | Design system preview |

## Configuration

Every setting is read from `.env`; see `.env.example` for the full list with comments.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string. Paste Neon's string as-is; the app switches it to the psycopg driver. |
| `SECRET_KEY` | Signs Flask's session cookie, which holds the sign-in, the cart and the CSRF token |
| `SESSION_COOKIE_SECURE` | `1` in production (HTTPS): session and "Keep me signed in" cookies are sent over HTTPS only |

A `DATABASE_URL` set in your shell overrides `.env`. That makes it easy to try migrations on a throwaway local database before touching Neon:

```bash
createdb keyora_check
DATABASE_URL=postgresql://localhost/keyora_check .venv/bin/flask --app run db upgrade
```

## Database migrations

```bash
.venv/bin/flask --app run db migrate -m "describe the change"   # after editing app/models.py; review the file
.venv/bin/flask --app run db upgrade
.venv/bin/flask --app run db downgrade                           # roll back one step
```

Better Auth's old tables (`user`, `session`, `account`, `verification`) are still in databases that used it. Alembic ignores them; once you're happy with the switch, drop them by hand (see CLAUDE.md).

## Project structure

```
app/
  __init__.py        create_app(): config, db, migrate, CSRF, auth hooks, blueprints, money filter
  config.py          settings from .env
  models.py          catalog, User / UserSession, Address, Order, AdminLog
  catalog.py         all catalog queries (routes call these; templates never query)
  seed.py            `flask seed` sample catalog
  images.py          Unsplash URL / srcset helpers (template globals)
  auth/              Flask-Login setup, account service (passwords, sessions, lockout), CLI commands
  main/              homepage, product page, styleguide; data.py = editorial content
  cart/              session cart (store.py) and routes
  checkout/          checkout preview: validation, provinces, delivery fee, thank-you
  account/           account pages; service.py = address queries
  templates/         Jinja templates, one folder per blueprint; components/ = shared macros
  static/src/        Tailwind entry (input.css), tokens (theme.css), base.css, components.css
migrations/          Alembic migrations
run.py               Flask entry point
```

## Design system

Tokens live in `app/static/src/theme.css`: a neutral palette, one blue accent, a type scale that resizes with the screen, and spacing and layout widths. Reusable classes live in `components.css`, for example `container-page`, `section`, `btn btn-primary`, `product-card`, `media`, `badge-*`, `chip`, `qty-stepper`, `option-card` and `notice-*`.

Tailwind's default colour palette is switched off, so use the project's named colours (`ink`, `muted`, `surface`, `accent`, `sale`, …). Write class names out in full in templates, because Tailwind can't detect names built with Jinja.

## Status and roadmap

Done: storefront, categories, search, cart, KHQR checkout, accounts with saved addresses and order history, and the admin.

Not built yet:
- Password reset, email verification and social sign-in
- Pre-filling checkout from the signed-in account
- An automated test suite

## Going to production

- Generate a strong `SECRET_KEY`. Set `SESSION_COOKIE_SECURE=1` and serve the site over HTTPS only.
- Put Flask behind `werkzeug.middleware.proxy_fix.ProxyFix`, so the admin's device list shows each visitor's real IP.
- Run Flask with a production WSGI server (e.g. gunicorn) instead of `run.py`.
- Change the seeded accounts' passwords, and set the real pickup address (`PICKUP_LOCATION` in `app/checkout/forms.py`).
