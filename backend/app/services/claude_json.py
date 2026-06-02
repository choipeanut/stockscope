"""Shared Claude JSON helper — robust parsing + timeout + transient retry.

Both the per-ticker and the market sentiment analyses ask Claude for a single
JSON object. The call used to fail *intermittently* ("sentiment unavailable")
for three avoidable reasons:

  1. Claude occasionally prefixes a sentence or wraps the JSON in a ```json
     fence → the old `raw.startswith("```")` check missed it and json.loads
     choked on the prose.
  2. No request timeout → a slow call on the small box could stall/abort.
  3. No retry → a transient 429 (rate limit) / 529 (overloaded) / timeout
     surfaced as a hard failure.

This helper fixes all three so the feature works consistently.
"""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0   # seconds per attempt — keep requests snappy on a small box
_RETRIES = 2      # extra attempts on transient errors


def extract_json(raw: str) -> dict:
    """Parse the first JSON object from a model response, tolerating code
    fences and surrounding prose."""
    s = (raw or "").strip()

    # If fenced, take the first fenced block's body.
    if "```" in s:
        parts = s.split("```")
        if len(parts) >= 2:
            body = parts[1]
            if body.lstrip().lower().startswith("json"):
                body = body.lstrip()[4:]
            s = body.strip()

    try:
        return json.loads(s)
    except Exception:
        # Fall back: slice from the first '{' to the last '}'.
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1 and j > i:
            return json.loads(s[i : j + 1])
        raise


def _is_transient(e: Exception) -> bool:
    name = type(e).__name__
    if any(k in name for k in (
        "RateLimit", "Overloaded", "APITimeout", "APIConnection", "InternalServer"
    )):
        return True
    msg = str(e).lower()
    return any(k in msg for k in ("429", "529", "overloaded", "timeout", "timed out"))


def call_claude_json(
    api_key: str,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 512,
) -> dict:
    """Call Claude and return the parsed JSON dict.

    Retries transient API errors (rate limit / overloaded / timeout) with a
    short backoff. Raises on unrecoverable failure (caller maps to
    'unavailable')."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=_TIMEOUT)
    last_err: Exception = RuntimeError("unknown")
    for attempt in range(_RETRIES + 1):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return extract_json(msg.content[0].text)
        except Exception as e:
            last_err = e
            if attempt < _RETRIES and _is_transient(e):
                logger.info("claude transient error (%s), retry %d/%d",
                            type(e).__name__, attempt + 1, _RETRIES)
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_err
