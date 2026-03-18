from __future__ import annotations

import time


ALLOWED_WAIT_UNTIL = {"commit", "domcontentloaded", "load", "networkidle"}


def fetch_html_with_playwright(
    url: str,
    timeout_ms: int = 30000,
    wait_until: str = "networkidle",
    retries: int = 1,
    retry_delay_ms: int = 1000,
    extra_wait_ms: int = 0,
    user_agent: str | None = None,
) -> str:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Playwright is not installed. Install it with 'pip install playwright' and run 'playwright install'."
        ) from exc

    wait_mode = wait_until if wait_until in ALLOWED_WAIT_UNTIL else "networkidle"
    total_attempts = max(retries, 0) + 1
    last_error: Exception | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for attempt in range(1, total_attempts + 1):
                page = browser.new_page(user_agent=user_agent) if user_agent else browser.new_page()
                try:
                    page.goto(url, wait_until=wait_mode, timeout=timeout_ms)
                    if extra_wait_ms > 0:
                        page.wait_for_timeout(extra_wait_ms)
                    return page.content()
                except (PlaywrightTimeoutError, Exception) as exc:  # noqa: PERF203
                    last_error = exc
                    if attempt < total_attempts:
                        delay_seconds = max(retry_delay_ms, 0) / 1000.0
                        time.sleep(delay_seconds)
                finally:
                    page.close()
        finally:
            browser.close()

    detail = str(last_error) if last_error else "unknown error"
    raise RuntimeError(f"Playwright fetch failed after {total_attempts} attempts: {detail}")
