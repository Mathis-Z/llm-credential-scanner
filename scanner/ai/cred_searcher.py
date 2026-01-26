"""
CredSearcher module. Takes keywords from the KeywordExtractor module and performs a web search
to find potential default credentials.
"""

import time
from threading import Thread, Event
import logging
from pubsub import pub
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from peewee import fn, Case
from scanner.ai.llm import get_chat_model
from scanner.ai.tools import search_web, fetch_url
from scanner.db.models import Service, Endpoint
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
    def __init__(self):
        super().__init__()
        self.termination_event = Event()
        self.keyword_extractor_done_event = Event()
        pub.subscribe(self._on_abort, 'abort')
        pub.subscribe(self.keyword_extractor_done_event.set, 'keyword_extractor.done')

    def run(self):
        while not self.termination_event.is_set():
            # Only select services for which *all* endpoints have non-NULL keywords.
            # i.e. there must be at least one endpoint with keywords, and zero endpoints with NULL keywords.
            # LLM-generated tbh

            ready_services = (
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
                                    ((Endpoint._keywords.is_null(False), 1),),
                                    None
                                )
                            ) > 0
                        )
                        .having(
                            fn.COUNT(
                                Case(
                                    None,
                                    ((Endpoint._keywords.is_null(True), 1),),
                                    None
                                )
                            ) == 0
                        )
                    )
                )
            )

            if len(ready_services) == 0 and self.keyword_extractor_done_event.is_set():
                break

            for service in ready_services:
                self.search_service(service)

            time.sleep(2)

        pub.sendMessage('cred_searcher.done')
        logger.info("CredSearcher exited")

    def _on_abort(self):
        self.termination_event.set()

    def search_service(self, service: Service):
        """Search default credentials for a service using its keywords"""
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

            llm = get_chat_model(reasoning=True)
            prompt = PROMPT_TEMPLATE % "\n".join(keywords)
            logger.debug("CredSearcher prompt for service %s:\n%s", service.url(), prompt)
            agent = create_agent(llm, tools=[search_web, submit_credentials, fetch_url])

            # https://docs.langchain.com/oss/python/langchain/agents#streaming
            for chunk in agent.stream({"messages": [{"role": "user", "content": prompt}]}, stream_mode="values"):
                # Each chunk contains the full state at that point
                latest_message = chunk["messages"][-1]

                logger.debug("---------------------------- Chunk ----------------------------")
                if isinstance(latest_message, ToolMessage):
                    logger.debug("Tool: %s", latest_message.content[:100])
                elif isinstance(latest_message, HumanMessage):
                    logger.debug("User: %s", latest_message.content)
                elif isinstance(latest_message, AIMessage):
                    if latest_message.tool_calls:
                        stringified_tool_calls = ', '.join([f"{tc['name']}({tc['args']})" for tc in latest_message.tool_calls])
                        logger.debug("AI: [Calling tools: %s]", stringified_tool_calls)
                    else:
                        logger.debug("AI: %s", latest_message.content)
        except Exception as e:
            logger.error("Error in CredSearcher for service %s: %s", service.url(), str(e))
