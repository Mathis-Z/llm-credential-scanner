# URL fetching via pooled browsers with JavaScript rendering support.

import concurrent.futures
import logging
import threading
import time
import simhash

from seleniumbase.fixtures import page_actions
from scanner.shared.browser_pool import BrowserPool

logger = logging.getLogger("scanner.shared.fetching")


def fetch_url_with_browser(
        start_url: str,
        acquire_timeout: float = 600,
        page_load_timeout: float = 10
    ) -> tuple[str, str]:
    """
    Fetch URL using pooled browser, render JavaScript, wait for DOM to settle.

    Returns (final_url, html) after all dynamic content loads.
    Falls back to (start_url, "") on failure.
    """
    logger.debug("Fetching URL: %s", start_url)
    try:
        with BrowserPool().acquire(timeout=acquire_timeout) as sb:
            return _load_page(sb, start_url, page_load_timeout)
    except TimeoutError:
        logger.error("Timed out waiting for a browser to fetch %s", start_url)
        return start_url, ""
    except Exception:
        logger.exception("Failed to fetch URL %s via pooled browser", start_url)
        return start_url, ""


def fetch_urls_with_browser(
        urls: list[str],
        acquire_timeout: float = 120,
        page_load_timeout: float = 10,
    ) -> list[tuple[str, str] | None]:
    """
    Fetch multiple URLs in parallel using pooled browsers.

    Waits up to acquire_timeout seconds for the first browser instance to become
    available across the whole batch. Once any fetch has successfully acquired a
    browser, the pool has proven itself functional, so the remaining fetches wait
    as long as necessary for their turn instead of being bound by that deadline.
    Failed fetches - including ones that never got a browser in time - are None.
    Results are returned in the same order as the input URLs.
    """
    if not urls:
        return []

    pool_confirmed = threading.Event()
    batch_deadline = time.monotonic() + acquire_timeout

    def fetch_one(url: str) -> tuple[str, str] | None:
        while True:
            wait = None if pool_confirmed.is_set() else max(0.0, batch_deadline - time.monotonic())
            try:
                with BrowserPool().acquire(timeout=wait) as sb:
                    pool_confirmed.set()
                    return _load_page(sb, url, page_load_timeout)
            except TimeoutError:
                if pool_confirmed.is_set():
                    continue  # a browser was acquired elsewhere in the meantime; keep waiting for ours
                logger.error("No browser became available within %ss to fetch %s", acquire_timeout, url)
                return None
            except Exception as e:
                truncated_error = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
                logger.error("Failed to fetch URL %s via pooled browser: %s", url, truncated_error)
                return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(urls)) as executor:
        return list(executor.map(fetch_one, urls))


def _load_page(sb, start_url: str, page_load_timeout: float) -> tuple[str, str]:
    """Load a URL in an already-acquired browser and return (final_url, html) once the DOM settles."""
    # UC mode stops the chromedriver service between commands, so raw
    # sb.driver.* calls hit a closed port. set_page_load_timeout has no sb.*
    # wrapper, so reconnect the service first; then use sb.open() (which
    # reconnects on its own) instead of sb.driver.get().
    page_actions._reconnect_if_disconnected(sb.driver)
    sb.driver.set_page_load_timeout(page_load_timeout)
    sb.open(start_url)
    sb.sleep(3)
    _wait_for_dom_settle(sb)
    raw = sb.get_page_source()
    current_url = sb.get_current_url()
    return current_url, raw


def _wait_for_dom_settle(sb, timeout_ms: int = 2000, stable_ms: int = 300) -> None:
    """
    Wait for DOM to stop changing using simhash distance comparison.
    
    Pages that continue changing (animations, live updates) will timeout
    after timeout_ms and return with whatever content is available.
    """
    start = time.time()
    last_html = sb.get_page_source()
    while True:
        time.sleep(stable_ms / 1000)
        current_html = sb.get_page_source()
        distance = simhash.Simhash(current_html).distance(simhash.Simhash(last_html))
        if distance < 20:
            return
        logger.debug("DOM still settling, simhash distance: %d", distance)
        last_html = current_html
        if (time.time() - start) * 1000 > timeout_ms:
            return
