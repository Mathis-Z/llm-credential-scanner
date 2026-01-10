"""
Keyword Extraction Module.
Uses the LLM to extract keywords from page source.
"""

from threading import Thread, Event
from typing import Any
import logging
import queue
import time
from pubsub import pub
from markdownify import markdownify
from scanner.ai.llm import get_chat_model
from scanner.db.models import Endpoint

PROMPT_TEMPLATE = """
You are a pentester and have encountered an unknown web application. Your goal is to find documentation or source code for this application that might contain default credentials. For this you need to identify keywords or links for a web search. The keywords/links must be specific to this application. Do not include keywords that are unspecific or not informative. The web page has the following content:
<<<BEGIN CONTENT>>>
%s
<<<END CONTENT>>>
Your first line of output must contain the number of identified keywords/links as a decimal integer. The following lines should contain one keyword/link per line. If there are no specific keywords on the page, output 0. Output no more than 5 keywords.
"""

logger = logging.getLogger('scanner.keyword_extractor')

class KeywordExtractor(Thread):
    """
    KeywordExtractor module. Uses LLM to extract websearch-relevant keywords from endpoint page sources.
    Runs until abort message is received.
    """
    def __init__(self):
        super().__init__()
        self.termination_event = Event()
        self.queues: dict[Any, queue.Queue] = {} # one queue per service for balancing
        self.new_queues = [] # cannot modify dict while iterating, store new queues here
        pub.subscribe(self._on_abort, 'abort')
        pub.subscribe(self._on_endpoint_created, 'Endpoint.created')

    def run(self):
        while not self.termination_event.is_set():
            # add any new queues
            for service_pk, q in self.new_queues:
                self.queues[service_pk] = q

            for service, q in self.queues.items():
                try:
                    endpoint = q.get_nowait()
                    if endpoint:
                        self.extract_keywords(endpoint)
                except queue.Empty:
                    continue
                except queue.ShutDown:
                    self.queues.pop(service)
            time.sleep(0.5)
        logger.info("KeywordExtractor exited")

    def extract_keywords(self, endpoint: Endpoint):
        """
        Converts the page source of the endpoint to markdown and
        sends it to the LLM to extract keywords.
        Updates the endpoint with the extracted keywords.
        """
        llm = get_chat_model(reasoning=False)
        prompt = PROMPT_TEMPLATE % markdownify(endpoint.page_source)
        logger.debug("Extracting keywords for %s: \n%s", endpoint.url(), prompt)
        response = llm.invoke([("human", prompt)]).content
        if response is None: # aborted
            return
        lines = [line.strip() for line in response.split('\n')]

        keyword_count = int(lines[0])
        endpoint.keywords = [kw for kw in lines[1:keyword_count+1] if len(kw) > 3]
        endpoint.save()
        logger.info("Extracted keywords for %s: %s", endpoint.url(), endpoint.keywords)

    def _on_abort(self):
        self.termination_event.set()
        for q in self.queues.values():
            q.shutdown(immediate=True)

    def _on_endpoint_created(self, record: Endpoint):
        q = self.queues.get(record.service.pk)
        if q is not None:
            q.put(record)
        else:
            q = queue.Queue()
            q.put(record)
            self.new_queues.append((record.service.pk, q))
