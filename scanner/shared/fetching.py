# URL fetching via pooled browsers with JavaScript rendering support.

import logging
import time
import simhash

from scanner.shared.browser_pool import BrowserPool

logger = logging.getLogger("scanner.shared.fetching")


def fetch_url_with_browser(
        start_url: str,
        acquire_timeout: float = 60,
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
            sb.driver.set_page_load_timeout(page_load_timeout)
            sb.driver.get(start_url)
            sb.sleep(1)
            _wait_for_dom_settle(sb)
            raw = sb.get_page_source()
            current_url = sb.get_current_url()
            return current_url, raw
    except TimeoutError:
        logger.error("Timed out waiting for a browser to fetch %s", start_url)
        return start_url, ""
    except Exception:
        logger.exception("Failed to fetch URL %s via pooled browser", start_url)
        return start_url, ""


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
