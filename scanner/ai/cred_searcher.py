# Uses LLM agent to search for default credentials based on keywords extracted from the target service.

import time
from threading import Thread, Event
import logging
from pubsub import pub
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from scanner.ai.llm import get_chat_model
from scanner.ai.tools import search_web, fetch_url_as_markdown
from scanner.db.models import Service
from scanner.db import DBConnectionMixin


PROMPT_TEMPLATE = """
You are a blueteam pentester trying to find default credentials for an unknown web application.
From the web applications pages you have gathered the following keywords/links for a web search:
%s

Follow these steps to find the credentials:
1. Identify the official website or repository for the application.
2. Crawl the site or repository for any documentation, installation guides, or configuration files that might contain default credentials. Follow links if necessary.
3. Submit the found credentials using the submit_credentials tool.

Search the web using carefully chosen, descriptive queries.
Use the fetch_url tool to retrieve the content of promising links.
If you find unrelated content, try refining your search.
You may use tools multiple times. Do not give up quickly.
Submit the credentials using the submit_credentials tool once you find them.
"""

logger = logging.getLogger('scanner.cred_searcher')

class CredSearcher(DBConnectionMixin, Thread):
    """
    LLM-based credential searcher that uses web search to find default credentials.
    
    Processes services marked 'done' by KeywordExtractor. Searches for credentials based on keywords
    extracted from the service's web pages. Gives up after 3 attempts per service.
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

    def can_early_abort(self, service: Service):
        """Check if we already found working creds on another endpoint for that service, allowing early termination."""
        service = Service.get(Service.pk == service.pk)
        return service.endpoint_with_working_creds_found()

    def search_service(self, service: Service):
        """
        Use LLM agent to search for default credentials using service keywords.
        
        The agent uses web search and URL fetching tools to find documentation
        containing default credentials. Credentials are saved to the DB.
        """
        try:
            logger.debug("Starting CredSearcher for service %s", service.url())

            @tool(description="Submit credentials (username & password)")
            def submit_credentials(username: str, password: str):
                service.add_credentials((username, password))
                service.save()
                logger.info("Submitted credentials for service %s: %s / %s", service.url(), username, password)
                return {"message": f"Credentials for {username} submitted successfully."}

            keywords = service.gather_keywords()
            if not keywords:
                logger.warning("No keywords were found for service %s, skipping", service.url())
                if service.credentials is None:
                    service.credentials = []
                    service.save()
                return

            llm = get_chat_model(reasoning=False)
            prompt = PROMPT_TEMPLATE % "\n".join(keywords)
            logger.debug("CredSearcher prompt for service %s:\n%s", service.url(), prompt)
            agent = create_agent(llm, tools=[search_web, submit_credentials, fetch_url_as_markdown])

            for chunk in agent.stream({"messages": [{"role": "user", "content": prompt}]}, stream_mode="values"):
                latest_message = chunk["messages"][-1]

                logger.debug("---------------------------- Chunk ----------------------------")
                if isinstance(latest_message, ToolMessage):
                    logger.debug("Tool: %s [...]", latest_message.content.split('\n')[0])  # Log only the first line of tool messages to avoid clutter
                elif isinstance(latest_message, HumanMessage):
                    logger.debug("User: %s", latest_message.content)
                elif isinstance(latest_message, AIMessage):
                    if latest_message.tool_calls:
                        stringified_tool_calls = ', '.join([f"{tc['name']}({tc['args']})" for tc in latest_message.tool_calls])
                        logger.debug("AI: [Calling tools: %s]", stringified_tool_calls)
                    else:
                        logger.debug("AI: %s", latest_message.content)

                if self.can_early_abort(service):
                    logger.info("CredSearcher aborts early because working credentials have been found for the service.")
                    return
        except Exception as e:
            logger.error("Error in CredSearcher for service %s: %s", service.url(), str(e))
