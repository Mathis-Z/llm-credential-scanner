import threading
import logging
import time
import os
import queue
from pubsub import pub
import requests
from bs4 import BeautifulSoup

# relative to this file
WORDLIST_RELATIVE_PATH = 'wordlist.txt'

class WebEnumerator(threading.Thread):
    def __init__(self):
        super().__init__()
        self.workers = []
        self.netscan_done = False
        pub.subscribe(self._on_endpoint_detected, 'netscanner.endpoint.detected')
        pub.subscribe(self._on_netscan_done, 'netscanner.done')
        pub.subscribe(self._on_netscan_done, 'abort')

    def run(self):
        while not self.netscan_done:
            threading.Event().wait(1)

        for worker in self.workers:
            worker.join()

        pub.sendMessage('webenum.done')
        logging.info("WebEnumerator done.")

    def _on_endpoint_detected(self, host: str, port: int, https: bool):
        protcol = "https" if https else "http"
        base_url = f"{protcol}://{host}:{port}"

        new_worker = WebEnumWorker(base_url)
        new_worker.start()
        self.workers.append(new_worker)

    def _on_netscan_done(self):
        self.netscan_done = True


class WebEnumWorker(threading.Thread):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.url_queue = queue.Queue()

        pub.subscribe(self._on_abort, 'abort')

        # Resolve the absolute path of the wordlist file relative to this script
        script_dir = os.path.dirname(__file__)
        wordlist_abs_path = os.path.join(script_dir, WORDLIST_RELATIVE_PATH)
        self.load_wordlist(wordlist_abs_path)

    def _on_abort(self):
        self.url_queue.shutdown(immediate=True)

    def load_wordlist(self, wordlist_path: str):
        """Loads the wordlist from the specified path and populates the URL queue."""
        try:
            with open(wordlist_path, 'r', encoding='utf-8') as f:
                for line in f:
                    word = line.strip()
                    if word:
                        full_url = f"{self.base_url}/{word}"
                        self.url_queue.put(full_url)

        except FileNotFoundError:
            logging.error("Wordlist file not found: %s", wordlist_path)

    def run(self) -> list[str]:
        urls_tested = 0
        last_log_time = 0

        while True:
            try:
                url = self.url_queue.get()
            except queue.ShutDown:
                break

            try:
                response = requests.get(url, timeout=5, verify=False, allow_redirects=True)
            except:
                continue

            if response.status_code < 200 or response.status_code >= 300:
                continue

            url = response.url  # handle redirects
            self.add_links_to_queue(response) # handle BFS crawling

            if self.detect_login_panel(response):
                logging.info("Found directory with password input: %s", url)
                pub.sendMessage('webenum_login_panel_found', url=url)

            urls_tested += 1
            if time.time() - last_log_time > 5:
                logging.debug("WebEnumWorker tested %d paths on %s", urls_tested, self.base_url)
                last_log_time = time.time()

        logging.info("WebEnumWorker finished testing %d paths on %s", urls_tested, self.base_url)

    def detect_login_panel(self, response: requests.Response) -> bool:
        """Detects if the HTTP response contains a login panel."""
        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            return bool(soup.select("input[type=password]"))
        except Exception as e:
            logging.error("Error parsing HTML from %s: %s", response.url, str(e))
            return False

    def add_links_to_queue(self, response: requests.Response):
        """Extracts links from the HTTP response and adds them to the URL queue."""

        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link['href']

                if href.startswith('/'):
                    self.url_queue.put(f"{response.url}{href}")
        except Exception as e:
            logging.error("Error parsing HTML from %s: %s", response.url, str(e))
