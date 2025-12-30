import logging

import click
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from scanner.ai.tools import search_web, submit_credentials, fetch_url_summary
from scanner.ai.llm import get_chat_model


@click.command()
@click.option("--log-level", default="INFO", help="Logging level")
def main(log_level="INFO"):
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), None),
        format="[%(asctime)s][%(levelname)s] %(message)s",
    )

    llm = get_chat_model(reasoning=True)
    agent = create_agent(llm, tools=[search_web, submit_credentials, fetch_url_summary])

    app = "mailcow"

    prompt = f"""
    You are a blueteam pentester trying to find default credentials for a web application called "{app}".

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

    # https://docs.langchain.com/oss/python/langchain/agents#streaming
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
                stringified_tool_calls = ', '.join([f"{tc['name']}({tc['args']})" for tc in latest_message.tool_calls])
                logging.info("AI: [Calling tools: %s]", stringified_tool_calls)
            else:
                logging.info("AI: %s", latest_message.content)


if __name__ == "__main__":
    main()
