"""WSGI entrypoint for hosts that look for `wsgi:app` (Vercel finds this file automatically).

Local development still uses `python run.py`.
"""

from run import app  # noqa: F401
