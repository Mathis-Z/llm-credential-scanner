"""
CredSearcher module. Takes keywords from the KeywordExtractor module and performs a web search
to find potential default credentials.
"""

import time
from threading import Thread
import logging
from pubsub import pub
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from scanner.ai.llm import get_chat_model
from scanner.ai.tools import search_web, fetch_url_summary
from scanner.db.models import Service, Endpoint


from scanner.ai.tools import make_credential_testing_tools
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from selenium import webdriver


PROMPT = """
You are a blueteam pentester trying to test default credentials for a web application at "%s".
The default credentials you want to test are:
- Username: "%s"
- Password: "%s"

Follow these steps to test the credentials:
1. Get the login HTML.
2. Identify required form fields.
3. Send keys to the from fields using css selectors and the insert_text_into_field tool.
4. Submit the form using the click_button tool.
5. Get the resulting HTML and figure out if the login was successful.

You may use tools multiple times. Do not give up quickly.
Use the submit_credentials_validity tool to report whether the credentials were valid or not.
"""

logger = logging.getLogger('scanner.cred_tester')

class CredTester(Thread):
    def __init__(self):
        super().__init__()
        self.terminate = False
        pub.subscribe(self._on_abort, 'abort')

    def run(self):
        while not self.terminate:
            unresolved_login_panels: list[Endpoint] = (
                Endpoint.select()
                .where(Endpoint.is_login is True)
                .where(Endpoint.working_credentials != '')
            )

            for login_panel in unresolved_login_panels:
                for (username, password) in login_panel.untested_credentials():
                    self.test_credentials(login_panel, username, password)

            time.sleep(2)
        logger.info("CredTester exited")

    def _on_abort(self):
        self.terminate = True

    def test_credentials(self, endpoint: Endpoint, username: str, password: str):
        full_prompt = PROMPT % (endpoint.url(), username, password)
        creds_valid = None

        llm = get_chat_model(reasoning=True)

        options = webdriver.FirefoxOptions()
        options.add_argument("--headless")
        driver = webdriver.Firefox(options=options)
        driver.get(endpoint.url())

        tools = make_credential_testing_tools(driver)

        @tool
        def report_credential_validity(valid: bool):
            nonlocal creds_valid
            creds_valid = valid
            return f"You have reported the credentials to be {'valid' if valid else 'invalid'}."

        tools.append(report_credential_validity)
        agent = create_agent(llm, tools=tools)

        # https://docs.langchain.com/oss/python/langchain/agents#streaming
        try:
            for chunk in agent.stream({"messages": [{"role": "user", "content": full_prompt}]}, stream_mode="values"):
                # Each chunk contains the full state at that point
                latest_message = chunk["messages"][-1]

                logger.info("---------------------------- Chunk ----------------------------")
                if isinstance(latest_message, ToolMessage):
                    logger.info("Tool output: %s", latest_message.content)
                elif isinstance(latest_message, HumanMessage):
                    logger.info("User: %s", latest_message.content)
                elif isinstance(latest_message, AIMessage):
                    if latest_message.tool_calls:
                        stringified_tool_calls = ", ".join(
                            [f"{tc['name']}({tc['args']})" for tc in latest_message.tool_calls]
                        )
                        logger.info("AI: [Calling tools: %s]", stringified_tool_calls)
                    else:
                        logger.info("AI: %s", latest_message.content)
        finally:
            driver.quit()

        creds_str = f"{username}:{password}"
        if creds_valid:
            logger.info("Found working credentials for %s: %s", endpoint.url(), creds_str)
            endpoint.working_credentials = creds_str
        else:
            logger.info("Credentials %s do not work on %s", creds_str, endpoint.url())
            endpoint.add_tested_credentials((username, password))

        endpoint.save()
