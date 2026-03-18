from __future__ import annotations

import time

import requests


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)


def fetch_html(
    url: str,
    timeout_seconds: int = 20,
    retries: int = 1,
    retry_delay_seconds: float = 1.0,
    user_agent: str | None = None,
) -> str:
    attempts = max(retries, 0) + 1
    headers = {"User-Agent": user_agent or DEFAULT_USER_AGENT}
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=timeout_seconds, headers=headers)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= attempts:
                break
            backoff = retry_delay_seconds * attempt
            time.sleep(max(backoff, 0.1))

    assert last_error is not None
    raise last_error
