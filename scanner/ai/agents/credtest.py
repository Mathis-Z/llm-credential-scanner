import logging

import click
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from selenium import webdriver

from scanner.ai.tools import make_credential_testing_tools, submit_credentials_validity
from scanner.ai.llm import get_chat_model


@click.command()
@click.option("--log-level", default="INFO", help="Logging level")
def main(log_level="INFO"):
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), None),
        format="[%(asctime)s][%(levelname)s] %(message)s",
    )

    llm = get_chat_model(reasoning=True)
    url = "http://localhost:8000/login"
    username = "admin"
    password = "nsip"

    options = webdriver.FirefoxOptions()
    options.add_argument("--headless")
    driver = webdriver.Firefox(options=options)
    driver.get(url)

    tools = make_credential_testing_tools(driver)
    tools.append(submit_credentials_validity)
    agent = create_agent(llm, tools=tools)

    prompt = f"""
    You are a blueteam pentester trying to test default credentials for a web application at "{url}".
    The default credentials you want to test are:
    - Username: "{username}"
    - Password: "{password}"

    Follow these steps to test the credentials:
    1. Get the login HTML.
    2. Identify required form fields.
    3. Send keys to the from fields using css selectors and the insert_text_into_field tool.
    4. Submit the form using the click_button tool.
    5. Get the resulting HTML and figure out if the login was successful.

    You may use tools multiple times. Do not give up quickly.
    Use the submit_credentials_validity tool to report whether the credentials were valid or not.
    """

    # https://docs.langchain.com/oss/python/langchain/agents#streaming
    try:
        for chunk in agent.stream({"messages": [{"role": "user", "content": prompt}]}, stream_mode="values"):
            # Each chunk contains the full state at that point
            latest_message = chunk["messages"][-1]

            logging.info("---------------------------- Chunk ----------------------------")
            if isinstance(latest_message, ToolMessage):
                logging.info("Tool output: %s", latest_message.content)
            elif isinstance(latest_message, HumanMessage):
                logging.info("User: %s", latest_message.content)
            elif isinstance(latest_message, AIMessage):
                if latest_message.tool_calls:
                    stringified_tool_calls = ", ".join(
                        [f"{tc['name']}({tc['args']})" for tc in latest_message.tool_calls]
                    )
                    logging.info("AI: [Calling tools: %s]", stringified_tool_calls)
                else:
                    logging.info("AI: %s", latest_message.content)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
