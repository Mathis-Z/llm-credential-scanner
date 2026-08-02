# Singleton pool of Selenium browsers for parallel web interactions.

import logging
import queue
import sys
import atexit
import threading
from contextlib import contextmanager
from seleniumbase import SB
from selenium.common.exceptions import TimeoutException
from scanner.settings import get_settings

# Exceptions that should not cause browser replacement (handled by caller)
NON_CRITICAL_EXCEPTIONS = (
    RuntimeError,       # e.g. "Failed to load login panel"
    TimeoutException,   # Selenium timeout waiting for element
    ValueError,
    KeyError,
    AttributeError,
)

logger = logging.getLogger("scanner.shared.browser_pool")


class BrowserPool:
    """
    Thread-safe singleton pool of headless Chrome browsers.
    
    Manages a fixed number of browser instances for concurrent web operations.
    Browsers are reset between uses to ensure clean state.
    """
    _instance: "BrowserPool | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "BrowserPool":
        if cls._instance is not None:
            return cls._instance
        with cls._instance_lock:
            if cls._instance is not None:
                return cls._instance

            instance = super().__new__(cls)
            size = get_settings().max_webdrivers
            logger.info("Initializing browser pool with %d instances", size)
            instance._pool = queue.Queue(maxsize=size)
            for i in range(size):
                entry = instance._create_browser(i)
                if entry:
                    instance._pool.put(entry)
            instance._initialized = True
            instance._sb_contexts = []
            cls._instance = instance
            logger.info("Browser pool ready (%d/%d browsers)", instance._pool.qsize(), size)
            atexit.register(cls._instance.shutdown)
            return cls._instance

    def _create_browser(self, index: int = 0) -> tuple | None:
        """Create a headless Chrome browser with anti-detection flags."""
        try:
            sb_ctx = SB(
                uc=True,
                headless=True,
                page_load_strategy="eager",
                chromium_arg=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--no-zygote",
                    "--disable-dev-shm-usage",
                    "--ignore-certificate-errors",
                    "--allow-insecure-localhost",
                    "--allow-running-insecure-content",
                ],
            )
            sb = sb_ctx.__enter__()
            logger.debug("Browser %d ready", index)
            return (sb, sb_ctx)
        except Exception:
            logger.exception("Failed to create browser %d", index)
            return None

    def shutdown(self) -> None:
        """Close all browser instances on shutdown."""
        with self._instance_lock:
            if self._pool.empty():
                return
            logger.info("Shutting down browser pool")
            while not self._pool.empty():
                try:
                    entry = self._pool.get_nowait()
                    self._close_browser(entry)
                except queue.Empty:
                    break

    @contextmanager
    def acquire(self, timeout: float | None = None):
        """
        Acquire a browser from the pool for exclusive use.
        
        Returns browser to pool on exit, replacing if unhealthy.
        """
        try:
            entry = self._pool.get(block=True, timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"No browser became available within {timeout}s") from None

        # Check browser health before returning
        if not self._is_healthy(entry):
            entry = self._replace_entry(entry)

        try:
            yield entry[0]
        except NON_CRITICAL_EXCEPTIONS:
            raise
        finally:
            entry = self._reset_browser(entry)
            self._pool.put(entry)

    def _reset_browser(self, entry: tuple) -> tuple:
        """Clear browser state (storage, cookies) between uses."""
        sb, _ctx = entry
        try:
            sb.clear_local_storage()
            sb.clear_session_storage()
            # Use sb.* wrappers, not sb.driver.*: in UC mode the chromedriver
            # service is stopped between commands, so raw driver calls hit a
            # closed port. The wrappers reconnect first.
            sb.open("about:blank")
            sb.delete_all_cookies()
        except Exception:
            if not sys.is_finalizing():
                logger.warning("Failed to reset browser state", exc_info=True)
            return self._replace_entry(entry)
        return entry

    def _close_browser(self, entry: tuple) -> None:
        """Close a browser context."""
        _sb, ctx = entry
        try:
            ctx.__exit__(None, None, None)
        except Exception:
            logger.exception("Error closing browser")

    def _replace_entry(self, entry: tuple) -> tuple:
        """Replace crashed/unhealthy browser with fresh instance."""
        logger.warning("Replacing dead/crashed browser")
        self._close_browser(entry)
        new_entry = self._create_browser()
        if new_entry is None:
            raise RuntimeError("Failed to create replacement browser")
        return new_entry

    def _is_healthy(self, entry: tuple) -> bool:
        """Check if browser is responsive via simple JS execution."""
        sb, _ctx = entry
        try:
            # sb.execute_script reconnects the UC-mode service first; a raw
            # sb.driver.execute_script would hit a closed port.
            sb.execute_script("return 1")
            return True
        except Exception as e:
            logger.debug("Browser health check failed: %s: %s", type(e).__name__, e)
            return False
