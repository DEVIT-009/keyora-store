# Keyora

An e-commerce storefront for mechanical keyboards, built with Flask, Jinja2 and Tailwind CSS, backed by PostgreSQL, with customer accounts handled by [Better Auth](https://www.better-auth.com/).

## Features

- **Storefront**: an editorial homepage, product pages with colour × switch variants, live stock states (in stock, low stock, sold out, pre-order) and related products.
- **Cart**: session-based, so no database tables. Prices and stock are always re-read from the catalog, quantities are capped at what's available, and a free-shipping progress bar tracks the $99 threshold.
- **Checkout (preview)**: contact → shipping address (Cambodia's 25 provinces) → delivery or pickup → pay with KHQR, followed by a thank-you page. No order is saved, no payment is taken and stock isn't reserved yet.
- **Accounts**: register, sign in and out, edit your profile and password, and manage saved addresses with a default. Better Auth handles the accounts and Flask keeps its own Jinja pages.
- **Design system**: Tailwind v4 tokens and reusable components. `/styleguide` shows every one of them.
- **Security**: CSRF protection on every form, server-side validation, and safe redirects after sign-in. Address lookups are always limited to the signed-in user.

## Tech stack

| Layer | Tools |
|---|---|
| Web app | Flask 3 (app factory + Blueprints), Jinja2, Flask-WTF (CSRF) |
| Styling | Tailwind CSS v4 via `@tailwindcss/cli` |
| Database | PostgreSQL (Neon or local), Flask-SQLAlchemy (SQLAlchemy 2), psycopg 3, Flask-Migrate / Alembic |
| Auth | Better Auth 1.7 (Node), email + password |
| Images | Unsplash photo IDs, with responsive `srcset` |

## Architecture

```
Browser ──► Flask  (pages, forms, CSRF, catalog, cart, checkout, addresses)
              │  server-to-server HTTP, 127.0.0.1 only
              ▼
           auth-server/  (Node + Better Auth, /api/auth/*)
              │
              ▼
           PostgreSQL  ◄── Flask also reads and writes here
```

- The browser only ever talks to Flask. The account forms post to Flask, which calls Better Auth and passes Better Auth's session cookies back to the browser.
- On each request that carries a Better Auth cookie, Flask asks Better Auth (`/get-session`) who the user is. Flask never decodes those cookies itself.
- Better Auth owns the `user`, `session`, `account` and `verification` tables. Flask owns the catalog (`categories`, `products`, `product_variants`) and `addresses`, which links to Better Auth's user and is deleted along with it.

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (or pip)
- Node.js 22.18+, which runs the auth service's `.ts` files directly
- PostgreSQL 14+, either a [Neon](https://neon.tech) project or a local install

## Getting started

```bash
# 1. Install dependencies
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
npm install                          # Tailwind CLI
npm --prefix auth-server install     # Better Auth service

# 2. Configure
cp .env.example .env
# then set DATABASE_URL, SECRET_KEY, BETTER_AUTH_SECRET (openssl rand -base64 32), BETTER_AUTH_URL

# 3. Create the database schema. Order matters: addresses references Better Auth's user table.
npm --prefix auth-server run migrate       # Better Auth tables
.venv/bin/flask --app run db upgrade       # catalog + addresses
.venv/bin/flask --app run seed             # sample catalog (safe to re-run)
npm --prefix auth-server run seed:users    # optional: one admin + one customer account

# 4. Build CSS
npm run build:css
```

`seed:users` creates `admin@keyora.test` (admin) and `customer@keyora.test` (customer). It prints a random password for each new account once; set `SEED_ADMIN_PASSWORD` / `SEED_USER_PASSWORD` to choose your own. Running it again leaves existing accounts alone.

## Running locally

Run two processes, plus the CSS watcher while you edit templates:

```bash
npm --prefix auth-server run dev     # Better Auth on http://127.0.0.1:3005 (loopback only)
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
| `DATABASE_URL` | Postgres connection string, shared by Flask and the auth service. Paste Neon's string as-is; each side switches it to the driver it needs. |
| `SECRET_KEY` | Signs Flask's session cookie, which holds the cart and the CSRF token |
| `BETTER_AUTH_SECRET` | Better Auth signing and encryption secret (at least 32 characters) |
| `BETTER_AUTH_URL` | The public address of the **Flask** site. Auth cookies are issued for it. |
| `AUTH_SERVER_URL` / `AUTH_PORT` | Where Flask reaches the auth service (default `http://127.0.0.1:3005`) |

A `DATABASE_URL` set in your shell overrides `.env`. That makes it easy to try migrations on a throwaway local database before touching Neon:

```bash
createdb keyora_check
DATABASE_URL=postgresql://localhost/keyora_check npm --prefix auth-server run migrate
DATABASE_URL=postgresql://localhost/keyora_check .venv/bin/flask --app run db upgrade
```

## Database migrations

```bash
.venv/bin/flask --app run db migrate -m "describe the change"   # after editing app/models.py; review the file
.venv/bin/flask --app run db upgrade
.venv/bin/flask --app run db downgrade                           # roll back one step
npm --prefix auth-server run migrate                             # after changing Better Auth config (auth-server/auth.ts)
```

Alembic is set up to ignore Better Auth's tables, and the foreign keys pointing into them, so `db migrate` never tries to drop them.

## Project structure

```
app/
  __init__.py        create_app(): config, db, migrate, CSRF, auth hooks, blueprints, money filter
  config.py          settings from .env
  models.py          Category, Product, ProductVariant, Address
  catalog.py         all catalog queries (routes call these; templates never query)
  seed.py            `flask seed` sample catalog
  images.py          Unsplash URL / srcset helpers (template globals)
  auth/              Better Auth client (server-to-server) + current_user / login_required
  main/              homepage, product page, styleguide; data.py = editorial content
  cart/              session cart (store.py) and routes
  checkout/          checkout preview: validation, provinces, delivery fee, thank-you
  account/           account pages; service.py = address queries
  templates/         Jinja templates, one folder per blueprint; components/ = shared macros
  static/src/        Tailwind entry (input.css), tokens (theme.css), base.css, components.css
auth-server/
  auth.ts            Better Auth config (email + password, phone and role fields, cookie cache)
  server.ts          Node HTTP server bound to 127.0.0.1
  seed-users.ts      admin + customer seed accounts
migrations/          Alembic migrations
run.py               Flask entry point
```

## Design system

Tokens live in `app/static/src/theme.css`: a neutral palette, one blue accent, a type scale that resizes with the screen, and spacing and layout widths. Reusable classes live in `components.css`, for example `container-page`, `section`, `btn btn-primary`, `product-card`, `media`, `badge-*`, `chip`, `qty-stepper`, `option-card` and `notice-*`.

Tailwind's default colour palette is switched off, so use the project's named colours (`ink`, `muted`, `surface`, `accent`, `sale`, …). Write class names out in full in templates, because Tailwind can't detect names built with Jinja.

## Status and roadmap

Done: storefront, cart, checkout UI, Better Auth accounts with saved addresses, and admin/customer roles (stored only).

Not built yet:
- Saving orders, KHQR payment (build the code on the server and confirm payment with Bakong) and reducing stock
- Admin pages (the `admin` role exists, but nothing checks it yet)
- Password reset, email verification and social sign-in
- Pre-filling checkout from the signed-in account
- An automated test suite

## Going to production

- Generate strong `SECRET_KEY` and `BETTER_AUTH_SECRET` values. Set `SESSION_COOKIE_SECURE=True` and serve the site over HTTPS only.
- Serve Flask behind one domain. Keep the auth service private: only Flask should reach it.
- Put Flask behind `werkzeug.middleware.proxy_fix.ProxyFix`, so it sees each visitor's real IP. Better Auth's rate limiting depends on it.
- Run Flask with a production WSGI server (e.g. gunicorn) instead of `run.py`.
- Change the seeded accounts' passwords, and set the real pickup address (`PICKUP_LOCATION` in `app/checkout/forms.py`).
