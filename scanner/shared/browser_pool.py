import logging
import queue
import atexit
import threading
from contextlib import contextmanager
from seleniumbase import SB
from scanner.settings import Settings

logger = logging.getLogger("scanner.shared.browser_pool")


class BrowserPool:
    _instance: "BrowserPool | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "BrowserPool":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:  # double-checked locking
                    instance = super().__new__(cls)
                    instance._initialized = False
                    instance._sb_contexts = []
                    instance._init_lock = threading.Lock()
                    cls._instance = instance
                    atexit.register(cls._instance.shutdown)
        return cls._instance

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            size = Settings().max_webdrivers
            self._pool: queue.Queue = queue.Queue(maxsize=size)
            logger.info("Initializing browser pool with %d instances", size)
            for i in range(size):
                try:
                    sb_ctx = SB(
                        uc=True,
                        headless=True,
                        chromium_arg=[
                            "--disable-dev-shm-usage",
                            "--ignore-certificate-errors",
                            "--allow-insecure-localhost",
                            "--allow-running-insecure-content",
                        ],
                    )
                    sb = sb_ctx.__enter__()
                    self._sb_contexts.append(sb_ctx)
                    self._pool.put(sb)
                    logger.debug("Browser %d ready", i)
                except Exception:
                    logger.exception("Failed to create browser %d", i)
            self._initialized = True
            logger.info("Browser pool ready (%d/%d browsers)", self._pool.qsize(), size)

    def shutdown(self) -> None:
        with self._init_lock:
            if not self._initialized:
                return
            logger.info("Shutting down browser pool")
            while not self._pool.empty():
                try:
                    self._pool.get_nowait()
                except queue.Empty:
                    break
            for ctx in self._sb_contexts:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    logger.exception("Error closing browser during shutdown")
            self._sb_contexts.clear()
            self._initialized = False

    @contextmanager
    def acquire(self, timeout: float | None = None):
        self._ensure_initialized()
        try:
            sb = self._pool.get(block=True, timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"No browser became available within {timeout}s") from None
        try:
            yield sb
        finally:
            self._pool.put(sb)
