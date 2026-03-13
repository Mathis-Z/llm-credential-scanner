import logging
import time
import simhash

from scanner.shared.browser_pool import BrowserPool

logger = logging.getLogger("scanner.shared.fetching")


def fetch_url(start_url: str, acquire_timeout: float = 60.0) -> tuple[str, str]:
    """
    Fetch a URL using a pooled SeleniumBase browser.

    Blocks until a browser is available (up to *acquire_timeout* seconds).
    Returns (final_url, html) or (start_url, "") on failure.
    """
    logger.debug("Fetching URL: %s", start_url)
    try:
        with BrowserPool().acquire(timeout=acquire_timeout) as sb:
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
