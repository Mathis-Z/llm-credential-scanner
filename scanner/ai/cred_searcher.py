# Deterministic RAG pipeline: search, fetch, chunk, retrieve, and extract default credentials.

import re
import time
from threading import Thread, Event
import logging
from pubsub import pub

from scanner.ai.llm import get_chat_model
from scanner.ai.rag import Chunk, chunk_pages, retrieve_top_chunks
from scanner.ai.tools import search_web, fetch_urls_as_markdown
from scanner.db.models import Service
from scanner.db import DBConnectionMixin
from scanner.settings import get_settings


PROMPT_TEMPLATE = """
You are a blueteam pentester reviewing documentation excerpts for a web application to find its DEFAULT credentials (i.e. credentials that ship with the software out of the box, or that are given as examples in setup/installation docs).

Below are %d excerpts gathered from web search results and directly-linked documentation pages, each preceded by its source URL.

%s

**Task**
Carefully read the excerpts above. Identify any default username/password pairs mentioned for this application (e.g. "admin/admin", "default password: changeme", tokens/API keys presented as defaults). Ignore credentials that are clearly examples for unrelated products, or placeholders like "<your-password>".

**Output Format**
- If you find one or more default credential pairs, output ONE line per pair, in the exact format:
username:password
- Output NOTHING else on those lines - no explanation, no bullet points, no markdown.
- If no default credentials are present in the excerpts, output exactly the single word:
none

**Examples**
Example output with credentials found:
admin:admin
root:changeme

Example output with none found:
none
"""

REFINE_QUERY_PROMPT_TEMPLATE = """
You are helping a security auditor craft a single web search query to find the DEFAULT credentials of a specific web application (credentials that ship out of the box, or that are given as examples in the application's setup/installation documentation).

Here are keywords automatically extracted from the application's own pages:
%s

Write ONE concise web search query that would surface the application's official documentation or setup guides mentioning its default username and password. Prefer the application's name and product identifiers, combined with terms like "default password" or "default login".

**Rules**
- Output only plain search terms on a single line.
- No quotes, no boolean operators (AND/OR), no site: filters, no line breaks.
- Keep it focused - a handful of words, not a sentence.

Output ONLY the query text, nothing else.
"""

logger = logging.getLogger('scanner.cred_searcher')

_URL_SCHEME_RE = re.compile(r'^https?://')


class CredSearcher(DBConnectionMixin, Thread):
    """
    Deterministic RAG-based credential searcher.

    Processes services marked 'done' by KeywordExtractor. For each, performs two
    web searches (one built by concatenating the non-link keywords, and one where an
    LLM refines those keywords into a focused query), fetches the combined, deduplicated
    result pages plus any URLs found directly among the keywords, retrieves the chunks
    most likely to contain default credentials via local embeddings, and asks the LLM to
    extract them in a fixed, parseable format. Gives up after 3 attempts per service.
    """
    def __init__(self):
        super().__init__()
        self.termination_event = Event()
        self.keyword_extractor_done_event = Event()
        pub.subscribe(self._on_abort, 'abort')
        pub.subscribe(self.keyword_extractor_done_event.set, 'keyword_extractor.done')

    def run_with_db(self):
        # Track number of search attempts per service to enforce the 3-attempt limit
        services_search_count = {}

        while not self.termination_event.is_set():
            # Find services that are ready for credential search (keywords extracted, no creds found yet)
            ready_services = list(
                Service
                .select()
                .where(
                    Service.keyword_extraction_done == True
                    & Service._credentials.is_null()
                )
            )
            # Filter out services that already have working creds or exceeded retry limit
            ready_services = [s for s in ready_services
                              if not s.endpoint_with_working_creds_found()
                              and services_search_count.get(s.pk, 0) < 3
            ]

            if len(ready_services) == 0 and self.keyword_extractor_done_event.is_set():
                break

            for service in ready_services:
                if self.termination_event.is_set():
                    break
                self.search_service(service)
                services_search_count[service.pk] = services_search_count.get(service.pk, 0) + 1
                if services_search_count[service.pk] >= 3:
                    logger.info("CredSearcher giving up on service %s after %d attempts", service.url(), services_search_count[service.pk])
                    service.credentials = []
                    service.save()

            time.sleep(2)

        pub.sendMessage('cred_searcher.done')
        logger.info("CredSearcher exited")

    def _on_abort(self):
        self.termination_event.set()

    def search_service(self, service: Service):
        """
        Run the deterministic RAG pipeline for one service: search -> fetch -> chunk -> retrieve -> extract.

        Leaves service.credentials unset (None) on any pipeline failure so run_with_db's
        3-attempt retry can try again. Saves any found credentials to the DB.
        """
        try:
            logger.debug("Starting CredSearcher for service %s", service.url())

            if service.endpoint_with_working_creds_found():
                logger.info("Skipping CredSearcher for %s: working creds already found on another endpoint", service.url())
                return

            keywords = service.gather_keywords()
            if not keywords:
                logger.warning("No keywords were found for service %s, skipping", service.url())
                if service.credentials is None:
                    service.credentials = []
                    service.save()
                return

            settings = get_settings()
            keyword_links, keyword_terms = self.split_keywords(keywords)

            # Build two complementary queries: the deterministic keyword concatenation
            # and an LLM-refined query. De-dupe in case they come out identical.
            concat_query = self.build_search_query(keyword_terms)
            refined_query = self.refine_search_query(keyword_terms)
            queries = list(dict.fromkeys(q for q in (concat_query, refined_query) if q))
            logger.debug("CredSearcher search queries for %s: %s", service.url(), queries)

            # Run every query and pool the top results from each.
            results = []
            for q in queries:
                results.extend(self.run_web_search(q, settings.rag_num_search_results))
            if not results:
                logger.warning("No search results for service %s (queries: %s)", service.url(), queries)

            logger.debug("cred search web queries found these results: %s", results)

            search_urls = [r["href"] for r in results if r.get("href")]
            urls = list(dict.fromkeys(search_urls + keyword_links))  # de-dupe, preserve order

            logger.debug("cred search web query found these urls: %s", urls)

            pages = self.fetch_pages(urls, service)
            if not pages:
                logger.warning("Failed to fetch any usable pages for service %s", service.url())
                return

            chunks = chunk_pages(pages, chunk_size=settings.rag_chunk_size, chunk_overlap=settings.rag_chunk_overlap)
            if not chunks:
                logger.warning("No text chunks produced for service %s", service.url())
                return

            top_chunks = retrieve_top_chunks(query="default credentials", chunks=chunks, top_k=min(max(len(urls), 5), 20))
            if not top_chunks:
                logger.warning("Retrieval returned no chunks for service %s", service.url())
                return

            credentials = self.extract_credentials(service, top_chunks)
            if credentials is None:
                logger.warning("Could not parse a valid credentials response for service %s", service.url())
                return
            if not credentials:
                logger.info("No default credentials found in retrieved content for service %s", service.url())
                service._credentials = []
                service.save() # marks service as processed
                return

            for cred in credentials:
                service.add_credentials(cred)
            service.save()
            logger.info("Found credentials for service %s: %s", service.url(), credentials)
        except Exception as e:
            logger.error("Error in CredSearcher for service %s: %s", service.url(), str(e))

    @staticmethod
    def split_keywords(keywords: list[str]) -> tuple[list[str], list[str]]:
        """Split keywords into (link keywords, term keywords) based on whether they look like a URL."""
        cleaned = sorted({kw.strip() for kw in keywords if kw and kw.strip()})
        links = [kw for kw in cleaned if _URL_SCHEME_RE.match(kw)]
        terms = [kw for kw in cleaned if not _URL_SCHEME_RE.match(kw)]
        return links, terms

    def build_search_query(self, term_keywords: list[str]) -> str:
        """Combine non-link keywords into a single DDGS query string; always includes 'default credentials'."""
        mandatory_suffix = "default credentials"
        terms = " ".join(term_keywords)

        max_terms_chars = max(0, get_settings().rag_query_max_chars - len(mandatory_suffix) - 1)
        if len(terms) > max_terms_chars:
            terms = terms[:max_terms_chars].rsplit(" ", 1)[0]

        return f"{terms} {mandatory_suffix}".strip()

    def refine_search_query(self, term_keywords: list[str]) -> str | None:
        """
        Ask the LLM to turn the raw extracted keywords into a single, focused web-search
        query. Returns the query string, or None if there are no keywords or the LLM call
        fails / yields nothing usable (in which case the caller falls back to the
        deterministic concatenated query alone).
        """
        if not term_keywords:
            return None
        try:
            llm = get_chat_model(reasoning=False)
            prompt = REFINE_QUERY_PROMPT_TEMPLATE % "\n".join(term_keywords)
            response = llm.invoke([("human", prompt)]).content
            if not response:  # empty or aborted
                return None

            # Keep the first non-empty line and strip any wrapping quotes the LLM added.
            query = next((line.strip() for line in response.strip().splitlines() if line.strip()), "")
            query = query.strip('"\'').strip()
            if not query:
                return None

            max_chars = get_settings().rag_query_max_chars
            if len(query) > max_chars:
                query = query[:max_chars].rsplit(" ", 1)[0]
            return query
        except Exception as e:
            logger.warning("Query refinement failed for keywords %s: %s", term_keywords, str(e))
            return None

    def run_web_search(self, query: str, max_results: int) -> list[dict]:
        try:
            return search_web(query, max_results=max_results)
        except Exception as e:
            logger.warning("Web search failed for query '%s': %s", query, str(e))
            return []

    def fetch_pages(self, urls: list[str], service: Service) -> list[tuple[str, str]]:
        """Fetch markdown content for each URL in parallel; skips individual fetch failures."""
        contents = fetch_urls_as_markdown(urls, truncate=False)
        pages: list[tuple[str, str]] = []
        for url, content in zip(urls, contents):
            if content is None:
                logger.warning("Failed to fetch %s for service %s", url, service.url())
                continue
            if content.strip():
                pages.append((url, content))
        return pages

    def extract_credentials(self, service: Service, chunks: list[Chunk]) -> list[tuple[str, str]] | None:
        """
        Single non-agentic LLM call over the retrieved chunks.

        Returns a list of (username, password) tuples, [] if the LLM reported 'none',
        or None if the response couldn't be parsed even after one retry.
        """
        llm = get_chat_model(reasoning=False)
        prompt = PROMPT_TEMPLATE % (len(chunks), self._format_chunks(chunks))
        logger.debug("CredSearcher extraction prompt for %s:\n%s", service.url(), prompt)

        messages = [("human", prompt)]
        response = llm.invoke(messages).content
        if response is None:  # aborted
            return None

        logger.debug("LLM response for %s:\n%s", service.url(), response)
        credentials = self._parse_credentials_response(response)
        if credentials is None:
            logger.debug("LLM format error, retrying for %s", service.url())
            reminder = (
                "Your previous response was not in the required format. "
                "Respond with ONLY credential lines in the exact format 'username:password' "
                "(one pair per line), or the single word 'none' if no default credentials "
                "were found in the excerpts. Do not include any other text."
            )
            messages.append(("ai", response))
            messages.append(("human", reminder))

            response = llm.invoke(messages).content
            if response is None:
                return None
            logger.debug("LLM retry response for %s:\n%s", service.url(), response)
            credentials = self._parse_credentials_response(response)

        return credentials

    @staticmethod
    def _format_chunks(chunks: list[Chunk]) -> str:
        parts = [f"--- Excerpt {i} (source: {c.source_url}) ---\n{c.text}" for i, c in enumerate(chunks, start=1)]
        return "\n\n".join(parts)

    @staticmethod
    def _parse_credentials_response(response: str) -> list[tuple[str, str]] | None:
        """Parse 'username:password' lines or literal 'none'. Returns None on any malformed line."""
        lines = [line.strip() for line in response.strip().split('\n') if line.strip()]
        if not lines:
            return None
        if len(lines) == 1 and lines[0].lower() == 'none':
            return []

        credentials = []
        for line in lines:
            if line.lower() == 'none' or ':' not in line:
                return None
            username, _, password = line.partition(':')
            username, password = username.strip(), password.strip()
            if not username or not password:
                return None
            credentials.append((username, password))
        return credentials
