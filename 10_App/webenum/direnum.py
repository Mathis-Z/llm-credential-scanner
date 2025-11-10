from urllib import request
import os
import threading
import queue
import logging
from pubsub import pub
from bs4 import BeautifulSoup


class DirectoryEnumerator(threading.Thread):
    def __init__(self, base_url: str, callback=lambda _: None, workers=1):
        super().__init__()
        self.callback = callback
        self.url_queue = queue.Queue(maxsize=1000)
        self.workers = [DirectoryEnumWorker(self.url_queue, callback) for _ in range(workers)]
        self.wordlist_feeds = []
        self.add_base_url(base_url)

    def add_base_url(self, base_url: str, wordlist_path: str = 'wordlist.txt'):
        feed = WordlistFeed(base_url, wordlist_path, self.url_queue)
        feed.start()
        self.wordlist_feeds.append(feed)

    def run(self):
        for worker in self.workers:
            worker.start()

        for feed in self.wordlist_feeds:
            feed.join()
        self.url_queue.shutdown()

        for worker in self.workers:
            worker.join()

class WordlistFeed(threading.Thread):
    """Feeds URLs to the queue based on a wordlist file."""

    def __init__(self, base_url: str, wordlist_path: str, url_queue: queue.Queue):
        super().__init__()
        self.base_url = base_url
        self.wordlist_path = wordlist_path
        self.url_queue = url_queue

    def run(self):
        # Resolve the absolute path of the wordlist file relative to this script
        script_dir = os.path.dirname(__file__)
        wordlist_abs_path = os.path.join(script_dir, self.wordlist_path)

        try:
            wordlist_file = open(wordlist_abs_path, 'r', encoding='utf-8')
        except FileNotFoundError as e:
            logging.error("Wordlist file not found: %s", wordlist_abs_path)
            raise e

        self.url_queue.put(self.base_url)    # query root

        lines = wordlist_file.readlines()
        for idx, line in enumerate(lines):
            dir_name = line.strip()
            url = f"{self.base_url.rstrip('/')}/{dir_name.lstrip('/')}"
            self.url_queue.put(url)
            if (idx) % 20000 == 0:
                logging.debug("Wordlist feed for %s is %.2f%% done", self.base_url, idx / len(lines) * 100)


class DirectoryEnumWorker(threading.Thread):
    def __init__(self, url_queue: queue.Queue, callback):
        super().__init__()
        self.callback = callback
        self.url_queue = url_queue

    def run(self) -> list[str]:
        """Enumerates directories on the given base URL using the provided wordlist file."""
        found_dirs = []

        while True:
            try:
                url = self.url_queue.get()
            except queue.ShutDown:
                break

            try:
                response = request.urlopen(url, timeout=5)
            except:
                continue

            if response.status < 200 or response.status >= 300:
                continue

            soup = BeautifulSoup(response.read().decode('utf-8'), 'html.parser')
            if soup.select("input[type=password]"):
                self.callback(url)
                found_dirs.append(url)
                logging.info("Found directory with password input: %s", url)
                pub.sendMessage('webenum_login_panel_found', url=url)
