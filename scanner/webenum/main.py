"""
Web enum module.

This module waits for services detected by the netscan module and enumerates
them using directory brute-forcing (via wordlist.txt) and basic crawling.
It creates Endpoint records for all URLs that return a non-error status code
and detects pages containing password inputs (potential login panels).

Architecture:
- WebEnumerator: Main coordinator that spawns worker threads for each service
- WebEnumWorker: Per-service thread that performs directory enumeration and crawling
"""

import re
import hashlib
import threading
import logging
import time
import os
import queue
import warnings
import urllib.parse
from pubsub import pub
import requests
import simhash
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from markdownify import markdownify

from scanner.db.models import Endpoint, Service
from scanner.db import DBConnectionMixin
from scanner.ai.tools.url_fetching import fetch_url_with_browser
from scanner.settings import get_settings

# relative to this file
WORDLIST_RELATIVE_PATH = 'wordlist.txt'

logger = logging.getLogger('scanner.webenum')
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

class WebEnumerator(threading.Thread):
    """
    Main coordinator for web enumeration.
    
    This thread orchestrates the enumeration process by:
    1. Listening for new services discovered by netscan via pubsub
    2. Spawning a WebEnumWorker for each service (up to max_workers concurrent)
    3. Waiting for all workers to complete before signaling completion
    
    Uses a semaphore to limit concurrent workers and avoid overwhelming resources.
    """
    def __init__(self):
        super().__init__()
        self.workers = []
        self.pending_services: queue.Queue[Service] = queue.Queue()
        self.max_workers = max(1, get_settings().max_webenum_workers)
        self.worker_semaphore = threading.BoundedSemaphore(self.max_workers)
        self.dispatcher_thread: threading.Thread | None = None
        self.shutdown_event = threading.Event()
        pub.subscribe(self._on_service_created, 'Service.created')
        pub.subscribe(self.shutdown_event.set, 'netscanner.done')
        pub.subscribe(self.shutdown_event.set, 'abort')

    def run(self):
        """
        Main entry point for the enumerator thread.
        
        Starts a dispatcher thread that processes pending services,
        then waits for netscan completion before joining all workers.
        """
        self.dispatcher_thread = threading.Thread(
            target=self._dispatch_service_workers,
            name="webenum-dispatcher",
            daemon=True
        )
        self.dispatcher_thread.start()
        self.shutdown_event.wait()

        if self.dispatcher_thread:
            self.dispatcher_thread.join()

        for worker in self.workers:
            worker.join()

        pub.sendMessage('webenum.done')
        logger.info("WebEnumerator done.")

    def _on_service_created(self, record: Service):
        self.pending_services.put(record)

    def _dispatch_service_workers(self):
        """
        Continuously pulls services from the queue and spawns workers.
        Uses a semaphore to ensure we don't exceed max concurrent workers.
        """
        while True:
            try:
                service = self.pending_services.get(timeout=1)
            except queue.Empty:
                # Check if netscan is done; if so, exit the loop
                if self.shutdown_event.is_set():
                    break
                continue

            # Acquire semaphore before spawning worker (blocks if at capacity)
            self.worker_semaphore.acquire()
            new_worker = WebEnumWorker(service, self.worker_semaphore)
            new_worker.start()
            self.workers.append(new_worker)


class WebEnumWorker(DBConnectionMixin, threading.Thread):
    """
    Worker thread that performs directory enumeration on a single web service.
    
    This worker:
    1. Establishes a baseline "404" page simhash for soft 404 detection
    2. Populates a queue with paths from the wordlist plus discovered links
    3. Processes each path, rendering the page and checking for login forms
    4. Creates Endpoint records for valid pages
    
    Uses simhash for soft 404 detection (many apps return 200 for non-existent paths)
    and markdown hashing for deduplication of visually identical pages.
    """
    def __init__(self, service: Service, semaphore: threading.BoundedSemaphore):
        super().__init__()
        self.semaphore = semaphore  # Semaphore to release when worker completes
        self.service = service
        self.render_cache: dict[str, str] = {}  # Cache rendered HTML to avoid re-fetching
        # Pre-compute the simhash of a non-existent path for soft 404 detection
        # Some apps return 200 OK for any path, but with similar "not found" content
        self.not_found_simhash = self.get_404_simhash()
        self.path_queue = queue.Queue()
        self.enqueue_path('/')   # start with the root path

        pub.subscribe(self._on_abort, 'abort')

        # Resolve the absolute path of the wordlist file relative to this script
        script_dir = os.path.dirname(__file__)
        wordlist_abs_path = os.path.join(script_dir, WORDLIST_RELATIVE_PATH)
        self.load_wordlist(wordlist_abs_path)

    def _on_abort(self):
        """Gracefully shut down the path queue on abort signal."""
        self.path_queue.shutdown(immediate=True)

    def load_wordlist(self, wordlist_path: str):
        """
        Loads the wordlist from the specified path and populates the URL queue.
        """
        try:
            with open(wordlist_path, 'r', encoding='utf-8') as f:
                for line in f:
                    word = line.strip()
                    if word:
                        self.enqueue_path(word)

        except FileNotFoundError:
            logger.error("Wordlist file not found: %s", wordlist_path)

    def run_with_db(self) -> list[str]:
        """
        Main processing loop for the worker thread.
        
        Continuously dequeues paths, tests them, and stops after 1000 paths
        to avoid excessive load on the target service.
        """
        try:
            paths_tested = 0
            last_log_time = 0

            while True:
                try:
                    path = self.path_queue.get_nowait()
                    if not path.startswith('/'):
                        path = '/' + path
                except (queue.ShutDown, queue.Empty):
                    break

                paths_tested += 1
                # Log progress every 5 seconds to avoid log spam
                if time.time() - last_log_time > 5:
                    logger.debug("WebEnumWorker tested %d paths on %s", paths_tested, self.service.url())
                    last_log_time = time.time()

                # Cap the number of paths to test per service to limit load
                # This prevents infinite crawling and respects target resources
                if paths_tested > 1000:
                    logging.warning("WebEnumWorker reached 1000 paths tested on %s; stopping to avoid excessive load", self.service.url())
                    break

                self.process_path(path)

            logger.info("WebEnumWorker finished testing %d paths on %s", paths_tested, self.service.url())
            self.service.webenum_done = True
            self.service.save(only=[Service.webenum_done])
        finally:
            # Always release the semaphore so another worker can start
            self.semaphore.release()

    def normalize_path(self, raw_path: str) -> str:
        """
        Normalizes a path to ensure it starts with '/' and handles edge cases.
        
        Extracts the path component from a URL if necessary, defaulting to '/'
        for empty or None paths.
        """
        if not raw_path:
            return '/'
        parsed = urllib.parse.urlparse(raw_path)
        path = parsed.path or '/'
        if not path.startswith('/'):
            path = '/' + path
        return path

    def already_found(self, path: str) -> bool:
        """
        Checks if an endpoint with this path has already been discovered.
        
        Checks both the resolved 'path' and the originally requested 'initial_path'
        to handle redirects correctly.
        """
        normalized = self.normalize_path(path)
        return Endpoint.select().where(
            (Endpoint.service == self.service)
            & ((Endpoint.path == normalized) | (Endpoint.initial_path == normalized))
        ).exists()

    def enqueue_path(self, raw_path: str):
        """
        Adds a path to the processing queue if it hasn't been seen before.
        
        This prevents duplicate work when the same path is discovered multiple
        times through different links.
        """
        path = self.normalize_path(raw_path)
        if not self.already_found(path):
            self.path_queue.put(path)

    def process_path(self, initial_path: str):
        """
        Tests a single path and creates an Endpoint record if valid.
        
        The validation pipeline:
        1. Skip if already discovered
        2. Query the URL and render the page
        3. Skip if it's a 404 (including soft 404s)
        4. Skip if the content is a duplicate (same markdown hash)
        5. Extract links for BFS crawling
        6. Detect login forms
        7. Save the endpoint to the database
        """
        try:
            initial_path = self.normalize_path(initial_path)
            if self.already_found(initial_path):
                return

            endpoint_url = f"{self.service.url()}{initial_path}"
            result = self.query_url(endpoint_url)

            if result is None:
                return

            status_code, final_url, page_source = result
            # Check for 404 including soft 404s (pages that return 200 but look like error pages)
            if self.is_404_response(status_code, page_source):
                logging.debug("Path %s ignored because of soft 404 detection", initial_path)
                return

            # Deduplicate pages with identical content
            md_hash = self.create_markdown_hash(page_source)
            if self.md_hash_exists(md_hash):
                logging.debug("Path %s ignored because of md_hash deduplication", initial_path)
                return

            final_path = self.normalize_path(final_url)

            if self.already_found(final_path):
                # Log unusual case where a path redirects to an already known path
                logger.warning("Weird: Path %s on %s resolved to already known path %s", initial_path, self.service.url(), final_path)
                return

            # BFS crawling: discover new paths from links in the page
            for link in self.parse_links(final_url, page_source):
                if self.service.url() in link:
                    self.enqueue_path(link)

            # Detect login panels by looking for password input fields
            is_login = self.detect_password_input(final_url, page_source)
            if is_login:
                logger.info("Found directory with password input: %s", final_url)

            Endpoint.create(
                service=self.service,
                path=final_path,
                initial_path=initial_path,
                is_login=is_login,
                page_source=page_source,
                md_hash=md_hash
            )
        except Exception as e:
            logger.error("Error processing path %s on %s: %s", initial_path, self.service.url(), str(e))

    def query_url(self, url) -> None | tuple[int, str, str]:
        """
        Fetches and renders a URL, returning the status code, final URL, and rendered HTML.
        
        Returns None for:
        - Network errors
        - Non-2xx status codes
        - Non-text content types (images, videos, etc.)
        - Already discovered paths (to avoid duplicate work)
        
        Uses HTTP requests for initial check, then browser rendering for JavaScript-heavy pages.
        """
        try:
            response = requests.get(url, timeout=5, verify=False, allow_redirects=True)
        except:
            return None

        content_type = response.headers.get('content-type')
        # Skip binary content that we can't analyze
        if content_type and not "text/" in content_type.lower():
            return None

        # Only process successful responses
        if response.status_code < 200 or response.status_code >= 300:
            return None
        logger.info("Got response for %s with code %d", url, response.status_code)

        # Skip rendering if the final path is already known in the DB
        final_path = self.normalize_path(response.url)
        if self.already_found(final_path):
            logger.debug("Skipping rendering for known path %s", final_path)
            return None

        # Use render cache to avoid re-fetching the same URL
        if response.url in self.render_cache:
            return response.status_code, response.url, self.render_cache[response.url]

        # Fetch with browser to handle JavaScript-rendered pages
        final_url, rendered_html = fetch_url_with_browser(response.url)
        if not rendered_html:
            logger.warning("Failed to render HTML for %s", response.url)
            return None
        self.render_cache[response.url] = rendered_html
        return response.status_code, final_url, rendered_html

    def detect_password_input(self, url, content) -> bool:
        """
        Detects if the HTML contains a password input field.
        
        Used to identify potential login panels that may be testable
        with credentials discovered by the scanner.
        """
        try:
            soup = BeautifulSoup(content, 'html.parser')
            return bool(soup.select("input[type=password]"))
        except Exception as e:
            logger.error("Error parsing HTML from %s: %s", url, str(e))
            return False

    def parse_links(self, url, content) -> set[str]:
        """
        Extracts internal links from HTML for BFS crawling.
        
        Filters out:
        - External links (different domains)
        - Special URLs (mailto, tel, javascript, etc.)
        - Fragments (anchor links)
        """
        urls = set()
        try:
            soup = BeautifulSoup(content, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link['href'].strip()
                # Filter out non-http links and special URL schemes
                if not href.startswith(('http://', 'https://', '//', 'mailto:', 'tel:', '#', 'javascript:', 'data:', 'blob:')):
                    full_url = urllib.parse.urljoin(url, href)
                    # Remove fragment (everything after #)
                    full_url = full_url.split('#')[0]
                    if full_url:
                        urls.add(full_url)
        except Exception as e:
            logger.error("Error parsing HTML from %s: %s", url, str(e))
        logger.debug("Extracted %d links from %s: %s", len(urls), url, urls)
        return urls

    def get_404_simhash(self) -> simhash.Simhash:
        """
        Establishes a baseline for soft 404 detection by fetching a known non-existent path.
        
        Many web applications return HTTP 200 for non-existent pages but display
        a generic "not found" error page. This method computes the simhash of such
        a page so we can detect similar responses later.
        
        Also handles the edge case where non-existent paths redirect to login pages
        (e.g., apps that require authentication), recording those as valid endpoints.
        
        Returns None if soft 404 detection cannot be used for this service.
        """
        path = "/nonexistent_1769471273"
        before_url = f"{self.service.url()}{path}"
        try:
            after_url, html = fetch_url_with_browser(before_url)
            if not html:
                logger.warning("Failed to fetch HTML for 404 simhash from %s; disabling soft 404 detection", before_url)
                return None

            md_hash = self.create_markdown_hash(html)

            after_path = urllib.parse.urlparse(after_url).path
            normalized_after_path = self.normalize_path(after_path)
            after_path_is_duplicate = self.already_found(normalized_after_path) or self.md_hash_exists(md_hash)

            # Edge case: non-existent path returns a login page
            # This can happen when the app redirects all requests to login
            if self.detect_password_input(after_url, html) and not after_path_is_duplicate:
                if after_path == path:
                    logger.info("Non-existent path returned login page %s; recording login endpoint", after_url)
                else:
                    logger.info("Non-existent path redirected to login page %s; recording login endpoint", after_url)

                Endpoint.create(
                    service=self.service,
                    path=normalized_after_path,
                    initial_path=self.normalize_path(path),
                    is_login=True,
                    page_source=html,
                    md_hash=md_hash
                )

            # If the request was redirected, soft 404 detection may not work correctly
            # (e.g., the app redirects all 404s to the homepage or login)
            if after_path != path:
                logger.debug("Soft 404 detection encountered redirect from %s to %s; disabling soft 404 detection", before_url, after_url)
                return None

            return self.simhash(html)
        except Exception as e:
            logger.error("Error fetching 404 page from %s: %s; disabling soft 404 detection", before_url, str(e))
            return None

    def clean_html_for_simhash(self, html: str) -> str:
        """
        Cleans HTML to produce consistent simhash comparisons.
        
        Removes dynamic content that shouldn't affect similarity:
        - Scripts and styles (often change on each request)
        - Whitespace normalization
        """
        soup = BeautifulSoup(html, 'html.parser')
        for script_or_style in soup(['script', 'style', 'link']):
            script_or_style.decompose()
        text = soup.get_text()
        # Normalize whitespace to single spaces
        text = re.sub(r'\s+', ' ', text)
        return text

    def simhash(self, html: str) -> simhash.Simhash:
        """
        Computes the simhash of HTML content for similarity detection.
        
        Simhash allows fast approximate matching - pages with similar content
        will have similar hashes, enabling detection of soft 404s.
        """
        cleaned_html = self.clean_html_for_simhash(html)
        return simhash.Simhash(cleaned_html)

    def create_markdown_hash(self, html: str):
        """
        Creates an MD5 hash of the markdown-converted content for deduplication.
        
        Converting to markdown first removes styling differences, so visually
        identical pages produce the same hash regardless of HTML structure.
        """
        md = markdownify(html)
        whitespace_free_md = re.sub(r'\s+', '', md)
        return hashlib.md5(whitespace_free_md.encode()).hexdigest()

    def md_hash_exists(self, md_hash: str) -> bool:
        """Checks if an endpoint with this markdown hash already exists."""
        return Endpoint.select().where(Endpoint.md_hash == md_hash).count() > 0

    def is_404_response(self, status_code: int, html: str) -> bool:
        """
        Determines if a response should be treated as a 404.
        
        Handles both explicit 404 status codes and "soft 404s" -
        pages that return 200 but have content similar to the baseline
        "not found" page we fetched earlier.
        
        Uses a distance threshold of 5 for simhash comparison.
        """
        if status_code == 404:
            logger.warning("Received explicit 404 status code for %s; treating as not found", self.service.url())
            return True

        if not self.not_found_simhash or not html:
            # Soft 404 detection is disabled for this service
            logger.warning("Soft 404 detection is disabled for %s due to missing simhash or HTML content", self.service.url())
            return False

        response_simhash = self.simhash(html)
        distance = self.not_found_simhash.distance(response_simhash)
        if distance < 5:
            # Low distance means the page content is similar to our 404 baseline
            logger.info("Soft 404 detected for %s with simhash distance %d", self.service.url(), distance)
            return True
        return False
