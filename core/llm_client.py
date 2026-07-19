"""
llm_client.py
Thin wrapper around the Anthropic Messages API.

Design choice: the whole app must still be demoable and testable without an
API key (judges may not want to provision one), so every caller goes through
`complete()` and handles `None` as "no model available → use a deterministic
template fallback". No key is ever hardcoded; it is read only from the
environment.
"""
import json
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = os.environ.get("ANTHROPIC_API_VERSION", "2023-06-01")
MODEL = os.environ.get("STADIUM_ASSISTANT_MODEL", "claude-sonnet-4-5")

# Kept comfortably under common serverless duration caps (Vercel Hobby 10s,
# Render free-tier 30s). A slow model response degrades gracefully to the
# deterministic template fallback instead of the whole request timing out.
_REQUEST_TIMEOUT_SECONDS = 8

# Retry once on transient network errors with a short delay.
_MAX_RETRIES = 1
_RETRY_DELAY_SECONDS = 0.5


def is_configured() -> bool:
    """Return True if an Anthropic API key is present in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def complete(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 500,
) -> Optional[str]:
    """
    Send a prompt to the Anthropic Messages API and return the text response.

    Returns ``None`` if:
    - No API key is configured in the environment.
    - The HTTP request fails after retries (network error, timeout, 4xx/5xx).
    - The response body cannot be parsed.

    Callers must handle the ``None`` case with a deterministic fallback (see
    ``core/assistant.py``). This method never raises an exception past its own
    boundary.

    Parameters
    ----------
    system_prompt : str
        The system-role instructions for the model.
    user_message : str
        The user's input to process.
    max_tokens : int
        Upper bound on tokens in the model's reply.

    Returns
    -------
    Optional[str]
        The model's text response, or None on any failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }

    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        if attempt > 0:
            time.sleep(_RETRY_DELAY_SECONDS)
        try:
            resp = requests.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=payload,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
            text_blocks = [
                b["text"]
                for b in data.get("content", [])
                if b.get("type") == "text"
            ]
            return "\n".join(text_blocks).strip() or None

        except requests.exceptions.Timeout as exc:
            logger.warning("Anthropic API timeout (attempt %d/%d)", attempt + 1, _MAX_RETRIES + 1)
            last_exc = exc
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            logger.warning("Anthropic API HTTP %s (attempt %d/%d)", status, attempt + 1, _MAX_RETRIES + 1)
            # Don't retry 4xx client errors — they won't change on retry
            if exc.response is not None and 400 <= exc.response.status_code < 500:
                break
            last_exc = exc
        except (requests.exceptions.RequestException, KeyError, json.JSONDecodeError) as exc:
            logger.warning(
                "Anthropic API error (attempt %d/%d): %s",
                attempt + 1,
                _MAX_RETRIES + 1,
                exc,
            )
            last_exc = exc

    # All retries exhausted — caller falls back to deterministic template
    if last_exc:
        logger.info("LLM unavailable, falling back to template response: %s", last_exc)
    return None
