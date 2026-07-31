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

You are a pentester analyzing an unknown web application.
Given the page content above, identify search keywords or URLs that could locate documentation or source code containing default credentials for this specific application.

**Rules**
- Only include keywords/URLs specific to this application (app name, product identifiers, doc URLs)
- Exclude generic or uninformative terms
- If an application name is visible (title, logo, headings), always include it
- Output at most 5 keywords/URLs
- Output at least 1 keyword/URL

**Output Format**
Your first line of output must contain the number of identified keywords/links as a decimal integer.
The following lines should contain one keyword/link per line.

**Example Output**
2
ExampleApp
https://example.com/docs
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
        Extract keywords using the LLM, preferring the markdownified page content.

        If the markdown attempt finds no keywords (either a well-formed "0" response
        or unparseable output even after retry), falls back to a second attempt using
        the raw HTML - some pages carry app-identifying info only in attributes/structure
        that markdownify strips. Both attempts are capped to 32k characters.
        """
        try:
            markdown_content = markdownify(endpoint.page_source, strip=['img'])[:32000]
            keywords = self._extract_keywords_from_content(endpoint, markdown_content)

            if not keywords:
                logger.debug("No keywords found from markdown for %s; retrying with raw HTML", endpoint.url())
                raw_content = endpoint.page_source[:32000]
                html_keywords = self._extract_keywords_from_content(endpoint, raw_content)
                if html_keywords is not None:
                    keywords = html_keywords

            if keywords is None:
                logger.warning("Could not extract keywords for %s (LLM response unparseable)", endpoint.url())
                return

            endpoint.keywords = [kw for kw in keywords if len(kw) > 3]
            endpoint.save(only=[Endpoint._keywords])
            logger.info("Extracted keywords for %s: %s", endpoint.url(), endpoint.keywords)
        except Exception as e:
            logger.error("Error extracting keywords for %s: %s", endpoint.url(), str(e))

    def _extract_keywords_from_content(self, endpoint: Endpoint, content: str) -> list[str] | None:
        """
        Single LLM extraction attempt against the given content, with one retry on
        malformed output. Returns the parsed keyword list (possibly empty), or None
        if the LLM was aborted or its response was unparseable even after retry.
        """
        llm = get_chat_model(reasoning=False)
        prompt = PROMPT_TEMPLATE % content
        logger.debug("Extracting keywords for %s: \n%s", endpoint.url(), prompt)

        messages = [("human", prompt)]
        response = llm.invoke(messages).content
        if response is None:  # aborted
            return None

        logger.debug("LLM response for %s: \n%s", endpoint.url(), response)
        keywords = self._parse_keywords_response(response)
        if keywords is None:
            logger.debug("LLM format error, retrying for %s", endpoint.url())
            reminder = "Your previous response was not in the correct format. Please strictly follow the output format: the first line must be the number of keywords as a simple integer, followed by exactly one keyword per line."
            messages.append(("ai", response))
            messages.append(("human", reminder))

            response = llm.invoke(messages).content
            if response is None:
                return None

            logger.debug("LLM retry response for %s: \n%s", endpoint.url(), response)
            keywords = self._parse_keywords_response(response)

        return keywords

    @staticmethod
    def _parse_keywords_response(response: str) -> list[str] | None:
        """Parse 'count\\nkeyword1\\n...' output. Returns None if the format doesn't match."""
        try:
            lines = [line.strip() for line in response.split('\n') if line.strip()]
            keyword_count = int(float(lines[0]))
            return lines[1:keyword_count + 1]
        except (ValueError, IndexError):
            return None

    def _on_abort(self):
        self.termination_event.set()
