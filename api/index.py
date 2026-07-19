"""
api/index.py
Vercel serverless entrypoint. Vercel's Python runtime looks for a WSGI
callable named `app` in this file — we simply import the real Flask app
from the project root and re-export it. No logic lives here.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app import app  # noqa: E402,F401  (Flask app object, re-exported for Vercel)
