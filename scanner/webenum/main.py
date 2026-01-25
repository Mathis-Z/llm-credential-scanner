"""
Web enum module.
Waits for services detected by netscan module and enumerates them using
directory enum (wordlist.txt) and basic crawling. Creates Endpoint records
for all urls returning a non-error status code.
"""

import re
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

from scanner.db.models import Endpoint, Service
from scanner.db import DBConnectionMixin

# relative to this file
WORDLIST_RELATIVE_PATH = 'wordlist.txt'

logger = logging.getLogger('scanner.webenum')
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

class WebEnumerator(DBConnectionMixin, threading.Thread):
    """WebEnumerator module. Spawns a worker thread for each discovered web service."""
    def __init__(self):
        super().__init__()
        self.workers = []
        self.netscan_done = threading.Event()
        pub.subscribe(self._on_service_created, 'Service.created')
        pub.subscribe(self._on_netscan_done, 'netscanner.done')
        pub.subscribe(self._on_netscan_done, 'abort')

    def run(self):
        self.netscan_done.wait()

        for worker in self.workers:
            worker.join()

        time.sleep(10)  # wait a bit for last services to be created
        pub.sendMessage('webenum.done')
        logger.info("WebEnumerator done.")

    def _on_service_created(self, record: Service):
        new_worker = WebEnumWorker(record)
        new_worker.start()
        self.workers.append(new_worker)

    def _on_netscan_done(self):
        self.netscan_done.set()


class WebEnumWorker(threading.Thread):
    """Worker thread that enumerates directories and detects login panels on a given web service."""
    def __init__(self, service: Service):
        super().__init__()
        service.enum_in_progress = True
        service.save()
        self.service = service
        self.not_found_simhash = self.get_404_simhash() # for soft 404 detection
        self.path_queue = queue.Queue()
        self.path_queue.put('/')   # start with the root

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
                        self.path_queue.put(word)

        except FileNotFoundError:
            logger.error("Wordlist file not found: %s", wordlist_path)

    def run(self) -> list[str]:
        paths_tested = 0
        last_log_time = 0

        while True:
            try:
                path = self.path_queue.get_nowait()
                if not path.startswith('/'):
                    path = '/' + path
            except (queue.ShutDown, queue.Empty):
                break

            endpoint_url = f"{self.service.url()}{path}"
            response = self.query_url(endpoint_url)

            paths_tested += 1
            if time.time() - last_log_time > 5:
                logger.debug("WebEnumWorker tested %d paths on %s", paths_tested, self.service.url())
                last_log_time = time.time()

            if response is None or self.is_404_response(response):
                continue

            # handle redirects
            # TODO: this is duplicated with allow_redirects=True in query_url
            path = urllib.parse.urlparse(response.url).path
            path = re.sub(r'/+', '/', path)  # normalize multiple slashes

            if Endpoint.select().where((Endpoint.service == self.service) & (Endpoint.path == path)).count() != 0:
                continue # skip already known endpoints

            # handle BFS crawling
            for link in self.parse_links(response):
                if self.service.url() in link:
                    p = urllib.parse.urlparse(link).path
                    self.path_queue.put(p)

            is_login = self.detect_password_input(response)
            if is_login:
                logger.info("Found directory with password input: %s", endpoint_url)

            Endpoint.create(
                service=self.service,
                path=path,
                is_login=is_login,
                page_source=response.text
            )

        logger.info("WebEnumWorker finished testing %d paths on %s", paths_tested, self.service.url())
        self.service.enum_in_progress = False
        self.service.save()

    def query_url(self, url) -> None|requests.Response:
        """Query a URL and return the response if status code is 2xx, else None. Follows redirects."""
        try:
            response = requests.get(url, timeout=5, verify=False, allow_redirects=True)
        except:
            return None

        if response.status_code < 200 or response.status_code >= 300:
            return None
        logger.info(f"Got response for {url} with code {response.status_code}")
        return response

    def detect_password_input(self, response: requests.Response) -> bool:
        """Detects if the HTTP response contains a password input."""
        # TODO: what about JS-generated forms?
        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            return bool(soup.select("input[type=password]"))
        except Exception as e:
            logger.error("Error parsing HTML from %s: %s", response.url, str(e))
            return False

    def parse_links(self, response: requests.Response) -> list[str]:
        """Extracts links from the HTTP response for crawling."""
        urls = []
        netloc = urllib.parse.urlparse(response.url).netloc

        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link['href']

                if href.startswith('/'):
                    urls.append(f"{netloc}{href}")
        except Exception as e:
            logger.error("Error parsing HTML from %s: %s", response.url, str(e))

        return urls

    def get_404_simhash(self) -> simhash.Simhash:
        """Fetches a non-existent page to compute its simhash for soft 404 detection."""
        url = f"{self.service.url()}/nonexistent_{int(time.time())}"
        try:
            response = requests.get(url, timeout=5, verify=False, allow_redirects=True)
        except:
            return None
        return simhash.Simhash(response.text)

    def is_404_response(self, response: requests.Response) -> bool:
        """Determines if the response is a 404 based on simhash comparison."""
        if response.status_code == 404:
            return True

        response_simhash = simhash.Simhash(response.text)
        distance = self.not_found_simhash.distance(response_simhash)
        return distance < 5
