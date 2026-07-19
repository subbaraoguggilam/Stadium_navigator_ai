"""
llm_client.py
Thin wrapper around the Anthropic Messages API.

Design choice: the whole app must still be demoable and testable without an
API key (judges may not want to provision one), so every caller goes through
`complete()` and handles `None` as "no model available -> use a
deterministic template fallback". No key is ever hardcoded; it is read only
from the environment.
"""
import os
import json
import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("STADIUM_ASSISTANT_MODEL", "claude-sonnet-4-5")


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def complete(system_prompt: str, user_message: str, max_tokens: int = 500) -> str | None:
    """
    Returns the model's text response, or None if no API key is configured
    or the request fails. Callers must handle the None case with a
    deterministic fallback (see core/assistant.py).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }

    try:
        # Kept comfortably under common serverless duration caps (e.g.
        # Vercel Hobby's 10s default) so a slow model response degrades to
        # the deterministic template fallback instead of the whole request
        # timing out with a 504.
        resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        return "\n".join(text_blocks).strip() or None
    except (requests.RequestException, KeyError, json.JSONDecodeError):
        # Network/API issues never crash the assistant; caller falls back.
        return None
