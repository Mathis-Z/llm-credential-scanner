# Extracts application-specific keywords from endpoint pages to enable credential search.

from threading import Thread, Event
import logging
import time
from pubsub import pub
from markdownify import markdownify
from scanner.ai.llm import get_chat_model
from scanner.db.models import Endpoint, Service
from scanner.db import DBConnectionMixin

PROMPT_TEMPLATE = """
<<<BEGIN CONTENT>>>
%s
<<<END CONTENT>>>
You are a pentester and have encountered an unknown web application.
Your goal is to find documentation or source code for this application that might contain default credentials.
Identify keywords or links for a web search. If an application name appears (title, logo text, headings),
include it as a keyword even if it is the only one. The keywords/links must be specific to this application.
Do not include keywords that are unspecific or not informative.
The web page has the content given above.
Your first line of output must contain the number of identified keywords/links as a decimal integer. The following lines should contain one keyword/link per line.
If there are no specific keywords on the page, output 0. Output no more than 5 keywords.
"""

logger = logging.getLogger('scanner.keyword_extractor')

class KeywordExtractor(DBConnectionMixin, Thread):
    """
    Extracts web-searchable keywords from web application pages using LLM.
    
    Keywords are used by CredSearcher to find documentation containing default credentials.
    Runs after WebEnumerator completes and before CredSearcher starts.
    """
    def __init__(self):
        super().__init__()
        self.termination_event = Event()
        self.webenum_done_event = Event()
        pub.subscribe(self._on_abort, 'abort')
        pub.subscribe(self.webenum_done_event.set, 'webenum.done')

    def run_with_db(self):
        while not self.termination_event.is_set():
            # Find services where webenum is done but keyword extraction is not
            unfinished_services = list(
                Service
                .select()
                .where((Service.webenum_done == True)
                       & (Service.keyword_extraction_done == False)
                )
            )

            if len(unfinished_services) == 0 and self.webenum_done_event.is_set():
                break

            for service in unfinished_services:
                if self.termination_event.is_set():
                    break
                self.extract_keywords_for_service(service)
                service.keyword_extraction_done = True
                service.save(only=[Service.keyword_extraction_done])

            time.sleep(2)

        pub.sendMessage('keyword_extractor.done')
        logger.info("KeywordExtractor exited")

    def extract_keywords_for_service(self, service: Service):
        """Extract keywords from up to 10 most relevant endpoints of the service."""
        for endpoint in self.select_relevant_endpoints(service):
            if self.termination_event.is_set():
                return
            self.extract_keywords(endpoint)

    def select_relevant_endpoints(self, service: Service) -> list[Endpoint]:
        """
        Selects endpoints most likely to contain useful keywords.
        
        Prioritizes shallow paths (e.g., /login > /admin/settings/users) as they
        typically contain application names and branding information.
        """
        all_endpoints = list(service.endpoints.where(Endpoint._keywords.is_null(True)))
        non_empty_endpoints = [ep for ep in all_endpoints if ep.page_source and ep.page_source.strip()]
        # Sort by path depth (number of slashes) and take top 10
        depth_sorted = sorted(non_empty_endpoints, key=lambda ep: ep.path.strip('/').count('/'))
        return depth_sorted[:10]

    def extract_keywords(self, endpoint: Endpoint):
        """
        Convert endpoint page to markdown and extract keywords using LLM.
        
        LLM analyzes the page content to identify application-specific identifiers
        like product names, version numbers, or documentation links.
        """
        try:
            llm = get_chat_model(reasoning=False)
            prompt = PROMPT_TEMPLATE % markdownify(endpoint.page_source)
            logger.debug("Extracting keywords for %s: \n%s", endpoint.url(), prompt)
            response = llm.invoke([("human", prompt)]).content
            if response is None:  # aborted
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
