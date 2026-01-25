"""
CredSearcher module. Takes keywords from the KeywordExtractor module and performs a web search
to find potential default credentials.
"""

import time
import urllib.parse
from threading import Thread, Event
import logging
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
import simhash
from pubsub import pub
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from scanner.ai.llm import get_chat_model
from scanner.ai.tools import make_credential_testing_tools
from scanner.db.models import Endpoint
from scanner.db import DBConnectionMixin
from bs4 import BeautifulSoup


PROMPT_TEMPLATE = """
You are a blueteam pentester trying to test default credentials for a web application at "%s".
The default credentials you want to test are:
- Username: "%s"
- Password: "%s"

Follow these steps to test the credentials:
1. Identify required form fields.
2. Send keys to the from fields using css selectors and the insert_text_into_field tool.
3. Submit the form using the click_button tool. Then terminate without further output.

You may use tools multiple times. Do not give up quickly. ONLY CALL TOOLS ONE BY ONE.
After calling a tool, wait for the result before calling another tool.
The login page has the following HTML content:
<<<PAGE CONTENT>>>
%s
<<<END PAGE CONTENT>>>
"""

logger = logging.getLogger('scanner.cred_tester')

class CredTester(DBConnectionMixin, Thread):
    def __init__(self):
        super().__init__()
        self.termination_event = Event()
        self.cred_searcher_done_event = Event()
        pub.subscribe(self._on_abort, 'abort')
        pub.subscribe(self.cred_searcher_done_event.set, 'cred_searcher.done')

    def run(self):
        while not self.termination_event.is_set():
            unresolved_login_panels: list[Endpoint] = list(
                Endpoint.select()
                .where((Endpoint.is_login == True) & (Endpoint.working_credentials == ''))
            )
            panels_with_untested_creds = [panel for panel in unresolved_login_panels if len(panel.untested_credentials()) > 0]

            if len(panels_with_untested_creds) == 0 and self.cred_searcher_done_event.is_set():
                break

            for login_panel in panels_with_untested_creds:
                for (username, password) in login_panel.untested_credentials():
                    self.test_credentials(login_panel, username, password)

            self.termination_event.wait(3)

        pub.sendMessage('cred_tester.done')
        logger.info("CredTester exited")

    def _on_abort(self):
        self.termination_event.set()

    def test_credentials(self, endpoint: Endpoint, username: str, password: str):
        """
        Uses the LLM to test the given credentials on the given login panel endpoint.
        Success is determined by detecting a page change after submitting the login form.
        """
        logger.debug("Testing credentials %s:%s on %s", username, password, endpoint.url())

        options = webdriver.FirefoxOptions()
        options.add_argument("--headless")
        driver = webdriver.Firefox(options=options)
        driver.get(endpoint.url())

        # Remove all script tags and their contents from the HTML source (to prevent overloading LLM)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        for script in soup.find_all("script"):
            script.decompose()
        # store page info to compare with after tool calls
        before_url = driver.current_url
        before_raw_page_source = driver.page_source
        before_page_source = str(soup)
        before_path = urllib.parse.urlparse(driver.current_url).path
        before_title = driver.title
        before_cookies = driver.get_cookies()
        logger.debug(
            "Before submit: url=%s path=%s title=%s cookies=%s page_len=%s",
            before_url,
            before_path,
            before_title,
            [c.get("name") for c in before_cookies],
            len(before_raw_page_source or "")
        )

        full_prompt = PROMPT_TEMPLATE % (endpoint.url(), username, password, before_page_source)
        llm = get_chat_model(reasoning=False)
        tools = make_credential_testing_tools(driver)
        agent = create_agent(llm, tools=tools)

        # https://docs.langchain.com/oss/python/langchain/agents#streaming
        try:
            for chunk in agent.stream({"messages": [{"role": "user", "content": full_prompt}]}, stream_mode="values"):
                # Each chunk contains the full state at that point
                latest_message = chunk["messages"][-1]

                logger.debug("---------------------------- Chunk ----------------------------")
                if isinstance(latest_message, ToolMessage):
                    logger.debug("Tool output: %s", latest_message.content)
                elif isinstance(latest_message, HumanMessage):
                    logger.debug("User: %s", latest_message.content)
                elif isinstance(latest_message, AIMessage):
                    if latest_message.tool_calls:
                        stringified_tool_calls = ", ".join(
                            [f"{tc['name']}({tc['args']})" for tc in latest_message.tool_calls]
                        )
                        logger.debug("AI: [Calling tools: %s]", stringified_tool_calls)
                    else:
                        logger.debug("AI: %s", latest_message.content)
        finally:
            # wait for potential redirects or DOM updates triggered by form submission
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: urllib.parse.urlparse(d.current_url).path != before_path
                    or d.page_source != before_raw_page_source
                )
            except TimeoutException:
                pass
            time.sleep(1)
            # to compare with before_page_source need to remove script tags again
            soup = BeautifulSoup(driver.page_source, "html.parser")
            for script in soup.find_all("script"):
                script.decompose()
            after_page_source = str(soup)
            after_path = urllib.parse.urlparse(driver.current_url).path
            after_url = driver.current_url
            after_title = driver.title
            after_raw_page_source = driver.page_source
            after_cookies = driver.get_cookies()
            driver.quit()

        simhash_distance = simhash.Simhash(before_page_source).distance(simhash.Simhash(after_page_source))
        before_cookie_names = {c.get("name") for c in before_cookies}
        after_cookie_names = {c.get("name") for c in after_cookies}
        logger.debug(
            "After submit: url=%s path=%s title=%s cookies=%s page_len=%s new_cookies=%s removed_cookies=%s",
            after_url,
            after_path,
            after_title,
            [c.get("name") for c in after_cookies],
            len(after_raw_page_source or ""),
            sorted(after_cookie_names - before_cookie_names),
            sorted(before_cookie_names - after_cookie_names),
        )
        login_successful = (
            (before_path != after_path) or
            (simhash_distance > 32)
        )
        logger.debug("Login %s: before_path=%s after_path=%s simhash_distance=%s",
                     "successful" if login_successful else "failed",
                     before_path,
                     after_path,
                     simhash_distance
        )

        creds_str = f"{username}:{password}"
        if login_successful:
            logger.info("Found working credentials for %s: %s", endpoint.url(), creds_str)
            endpoint.working_credentials = creds_str
        else:
            logger.info("Credentials %s do not work on %s", creds_str, endpoint.url())
            endpoint.add_tested_credentials((username, password))

        endpoint.save()
