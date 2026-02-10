"""
Keyword Extraction Module.
Uses the LLM to extract keywords from page source.
"""

from threading import Thread, Event
import logging
import random
import time
from peewee import fn, Case
from pubsub import pub
from markdownify import markdownify
from scanner.ai.llm import get_chat_model
from scanner.db.models import Endpoint, Service
from scanner.db import DBConnectionMixin

PROMPT_TEMPLATE = """
You are a pentester and have encountered an unknown web application. Your goal is to find documentation or source code for this application that might contain default credentials. Identify keywords or links for a web search. If an application name appears (title, logo text, headings), include it as a keyword even if it is the only one. The keywords/links must be specific to this application. Do not include keywords that are unspecific or not informative. The web page has the following content:
<<<BEGIN CONTENT>>>
%s
<<<END CONTENT>>>
Your first line of output must contain the number of identified keywords/links as a decimal integer. The following lines should contain one keyword/link per line. If there are no specific keywords on the page, output 0. Output no more than 5 keywords.
"""

logger = logging.getLogger('scanner.keyword_extractor')

class KeywordExtractor(DBConnectionMixin, Thread):
    """
    KeywordExtractor module. Uses LLM to extract websearch-relevant keywords from endpoint page sources.
    Runs until abort message is received.
    """
    def __init__(self):
        super().__init__()
        self.termination_event = Event()
        self.webenum_done_event = Event()
        pub.subscribe(self._on_abort, 'abort')
        pub.subscribe(self.webenum_done_event.set, 'webenum.done')

    def run(self):
        while not self.termination_event.is_set():
            unfinished_services = (
                Service
                .select()
                .where(
                    (~Service.enum_in_progress)
                    & Service._credentials.is_null()
                    & Service.pk.in_(
                        Endpoint
                        .select(Endpoint.service_id)
                        .group_by(Endpoint.service_id)
                        .having(
                            fn.COUNT(
                                Case(
                                    None,
                                    ((Endpoint._keywords.is_null(), 1),),
                                    None
                                )
                            ) > 0
                        )
                    )
                )
            )

            if len(unfinished_services) == 0 and self.webenum_done_event.is_set():
                break

            for service in unfinished_services:
                if self.termination_event.is_set():
                    break
                self.extract_keywords_for_service(service)

            time.sleep(2)

        pub.sendMessage('keyword_extractor.done')
        logger.info("KeywordExtractor exited")

    def extract_keywords_for_service(self, service: Service):
        """
        Extract keywords for all endpoints of the given service that do not yet have keywords.
        """
        # TODO: make the selection of endpoints smarter
        # e.g. convert all endpoints to markdown, generate simhashes and then find the most
        # unique endpoints or something like that
        eps = list(service.endpoints)
        random.shuffle(eps)
        eps = eps[:10] # limit to 10 endpoints to avoid excessive API cost

        for endpoint in eps:
            if self.termination_event.is_set():
                return
            self.extract_keywords(endpoint)

    def extract_keywords(self, endpoint: Endpoint):
        """
        Converts the page source of the endpoint to markdown and
        sends it to the LLM to extract keywords.
        Updates the endpoint with the extracted keywords.
        """
        try:
            llm = get_chat_model(reasoning=False)
            prompt = PROMPT_TEMPLATE % markdownify(endpoint.page_source)
            logger.debug("Extracting keywords for %s: \n%s", endpoint.url(), prompt)
            response = llm.invoke([("human", prompt)]).content
            if response is None: # aborted
                return
            lines = [line.strip() for line in response.split('\n')]

            keyword_count = int(lines[0])
            endpoint.keywords = [kw for kw in lines[1:keyword_count+1] if len(kw) > 3]
            endpoint.save(only=[Endpoint._keywords])
            logger.info("Extracted keywords for %s: %s", endpoint.url(), endpoint.keywords)
        except Exception as e:
            logger.error("Error extracting keywords for %s: %s", endpoint.url(), str(e))

    def _on_abort(self):
        self.termination_event.set()
