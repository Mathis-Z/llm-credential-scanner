"""
Web enum module.
Waits for services detected by netscan module and enumerates them using
directory enum (wordlist.txt) and basic crawling. Creates Endpoint records
for all urls returning a non-error status code.
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
from scanner.settings import Settings

# relative to this file
WORDLIST_RELATIVE_PATH = 'wordlist.txt'

logger = logging.getLogger('scanner.webenum')
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

class WebEnumerator(threading.Thread):
    """WebEnumerator module. Spawns a worker thread for each discovered web service."""
    def __init__(self):
        super().__init__()
        self.workers = []
        self.pending_services: queue.Queue[Service] = queue.Queue()
        self.max_workers = max(1, Settings().max_webenum_workers)
        self.worker_semaphore = threading.BoundedSemaphore(self.max_workers)
        self.dispatcher_thread: threading.Thread | None = None
        self.netscan_done = threading.Event()
        pub.subscribe(self._on_service_created, 'Service.created')
        pub.subscribe(self._on_netscan_done, 'netscanner.done')
        pub.subscribe(self._on_netscan_done, 'abort')

    def run(self):
        self.dispatcher_thread = threading.Thread(
            target=self._dispatch_services,
            name="webenum-dispatcher",
            daemon=True
        )
        self.dispatcher_thread.start()
        self.netscan_done.wait()

        if self.dispatcher_thread:
            self.dispatcher_thread.join()

        for worker in self.workers:
            worker.join()

        pub.sendMessage('webenum.done')
        logger.info("WebEnumerator done.")

    def _on_service_created(self, record: Service):
        self.pending_services.put(record)

    def _on_netscan_done(self):
        self.netscan_done.set()

    def _dispatch_services(self):
        while True:
            try:
                service = self.pending_services.get(timeout=1)
            except queue.Empty:
                if self.netscan_done.is_set():
                    break
                continue

            self.worker_semaphore.acquire()
            new_worker = WebEnumWorker(service, self.worker_semaphore)
            new_worker.start()
            self.workers.append(new_worker)


class WebEnumWorker(DBConnectionMixin, threading.Thread):
    """Worker thread that enumerates directories and detects login panels on a given web service."""
    def __init__(self, service: Service, semaphore: threading.BoundedSemaphore):
        super().__init__()
        self.semaphore = semaphore
        self.service = service
        self.render_cache: dict[str, str] = {}
        self.not_found_simhash = self.get_404_simhash() # for soft 404 detection
        self.path_queue = queue.Queue()
        self.enqueue_path('/')   # start with the root

        pub.subscribe(self._on_abort, 'abort')

        # Resolve the absolute path of the wordlist file relative to this script
        script_dir = os.path.dirname(__file__)
        wordlist_abs_path = os.path.join(script_dir, WORDLIST_RELATIVE_PATH)
        self.load_wordlist(wordlist_abs_path)

    def _on_abort(self):
        self.path_queue.shutdown(immediate=True)

    def load_wordlist(self, wordlist_path: str):
        """Loads the wordlist from the specified path and populates the URL queue."""
        try:
            with open(wordlist_path, 'r', encoding='utf-8') as f:
                for line in f:
                    word = line.strip()
                    if word:
                        self.enqueue_path(word)

        except FileNotFoundError:
            logger.error("Wordlist file not found: %s", wordlist_path)

    def run_with_db(self) -> list[str]:
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
                if time.time() - last_log_time > 5:
                    logger.debug("WebEnumWorker tested %d paths on %s", paths_tested, self.service.url())
                    last_log_time = time.time()

                if paths_tested > 1000:
                    logging.warning("WebEnumWorker reached 1000 paths tested on %s; stopping to avoid excessive load", self.service.url())
                    break

                self.process_path(path)

            logger.info("WebEnumWorker finished testing %d paths on %s", paths_tested, self.service.url())
            self.service.webenum_done = True
            self.service.save(only=[Service.webenum_done])
        finally:
            self.semaphore.release()

    def normalize_path(self, raw_path: str) -> str:
        if not raw_path:
            return '/'
        parsed = urllib.parse.urlparse(raw_path)
        path = parsed.path or '/'
        if not path.startswith('/'):
            path = '/' + path
        return path

    def already_found(self, path: str) -> bool:
        normalized = self.normalize_path(path)
        return Endpoint.select().where(
            (Endpoint.service == self.service)
            & ((Endpoint.path == normalized) | (Endpoint.initial_path == normalized))
        ).exists()

    def enqueue_path(self, raw_path: str):
        path = self.normalize_path(raw_path)
        if not self.already_found(path):
            self.path_queue.put(path)

    def process_path(self, initial_path: str):
        try:
            initial_path = self.normalize_path(initial_path)
            if self.already_found(initial_path):
                return

            endpoint_url = f"{self.service.url()}{initial_path}"
            result = self.query_url(endpoint_url)

            if result is None:
                return

            status_code, final_url, page_source = result
            if self.is_404_response(status_code, page_source):
                logging.debug("Path %s ignored because of soft 404 detection", initial_path)
                return

            md_hash = self.create_markdown_hash(page_source)
            if self.md_hash_exists(md_hash):
                logging.debug("Path %s ignored because of md_hash deduplication", initial_path)
                return

            final_path = self.normalize_path(final_url)

            if self.already_found(final_path):
                logger.warning("Weird: Path %s on %s resolved to already known path %s", initial_path, self.service.url(), final_path)
                return # skip already known endpoints

            # handle BFS crawling
            for link in self.parse_links(final_url, page_source):
                if self.service.url() in link:
                    self.enqueue_path(link)

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
        """Query a URL and return (status_code, final_url, rendered_html) if status code is 2xx. Ignores anything with non-text content-type"""
        try:
            response = requests.get(url, timeout=5, verify=False, allow_redirects=True)
        except:
            return None

        content_type = response.headers.get('content-type')
        if content_type and not "text/" in content_type.lower():
            return None # ignore images, videos, ...

        if response.status_code < 200 or response.status_code >= 300:
            return None
        logger.info("Got response for %s with code %d", url, response.status_code)

        # Skip rendering if the final path is already known in the DB
        final_path = self.normalize_path(response.url)
        if self.already_found(final_path):
            logger.debug("Skipping rendering for known path %s", final_path)
            return None

        # TODO: maybe we can use the functools memoization for the fetch_url method instead?
        if response.url in self.render_cache:
            return response.status_code, response.url, self.render_cache[response.url]

        final_url, rendered_html = fetch_url_with_browser(response.url)
        if not rendered_html:
            logger.warning("Failed to render HTML for %s", response.url)
            return None
        self.render_cache[response.url] = rendered_html
        return response.status_code, final_url, rendered_html

    def detect_password_input(self, url, content) -> bool:
        """Detects if the HTML contains a password input."""
        try:
            soup = BeautifulSoup(content, 'html.parser')
            return bool(soup.select("input[type=password]"))
        except Exception as e:
            logger.error("Error parsing HTML from %s: %s", url, str(e))
            return False

    def parse_links(self, url, content) -> set[str]:
        """Extracts links from the HTML for crawling."""
        urls = set()
        try:
            soup = BeautifulSoup(content, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link['href'].strip()
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
        """Fetches a non-existent page to compute its simhash for soft 404 detection."""
        path = "/nonexistent_1769471273" # hardcoding to allow LLM response caching
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

            if after_path != path:
                # TODO: this is a rather lazy check for apps that redirect all or most requests to their login page
                logger.debug("Soft 404 detection encountered redirect from %s to %s; disabling soft 404 detection", before_url, after_url)
                return None

            return self.simhash(html)
        except Exception as e:
            logger.error("Error fetching 404 page from %s: %s; disabling soft 404 detection", before_url, str(e))
            return None

    def clean_html_for_simhash(self, html: str) -> str:
        """Cleans HTML content to improve simhash accuracy."""
        # Remove scripts and styles
        soup = BeautifulSoup(html, 'html.parser')
        for script_or_style in soup(['script', 'style', 'link']):
            script_or_style.decompose()
        text = soup.get_text()
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        return text

    def simhash(self, html: str) -> simhash.Simhash:
        """Computes the simhash of cleaned HTML content."""
        # TODO: evaluate other simhash techniques like tlsh
        # TODO: evaluate using just markdown content instead of full HTML
        cleaned_html = self.clean_html_for_simhash(html)
        return simhash.Simhash(cleaned_html)

    def create_markdown_hash(self, html: str):
        md = markdownify(html)
        whitespace_free_md = re.sub(r'\s+', '', md)
        return hashlib.md5(whitespace_free_md.encode()).hexdigest()

    def md_hash_exists(self, md_hash: str) -> bool:
        return Endpoint.select().where(Endpoint.md_hash == md_hash).count() > 0

    def is_404_response(self, status_code: int, html: str) -> bool:
        """Determines if the response is a 404 based on simhash comparison."""
        if status_code == 404:
            logger.warning("Received explicit 404 status code for %s; treating as not found", self.service.url())
            return True

        if not self.not_found_simhash or not html:
            logger.warning("Soft 404 detection is disabled for %s due to missing simhash or HTML content", self.service.url())
            return False

        response_simhash = self.simhash(html)
        distance = self.not_found_simhash.distance(response_simhash)
        if distance < 5:
            logger.info("Soft 404 detected for %s with simhash distance %d", self.service.url(), distance)
            return True
        return False
