"""
conftest.py
Shared pytest fixtures and path configuration for the test suite.

This file is automatically discovered by pytest and runs before any tests.
It ensures the project root is on sys.path so tests can import `app`,
`core.*`, etc. without needing per-file path hacks.
"""
import os
import sys

# Ensure project root is importable regardless of where pytest is invoked from
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Remove any real API key from the test environment so that all tests
# exercise the deterministic keyword / template fallback path by default.
# Tests that specifically want to mock an API key can set it locally.
os.environ.pop("ANTHROPIC_API_KEY", None)
