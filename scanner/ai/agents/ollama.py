import logging
from datetime import datetime
import ollama
from ddgs import DDGS
from scanner.ai.mcp.fetch_url import fetch_url

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s] %(message)s')

MODEL = "qwen3:8B-Q4_K_M"


def get_date():
    """
    Returns the current date and time.
    """
    return {"date": datetime.now().isoformat()}


def search_web(query: str):
    """
    Perform a web search using DuckDuckGo library
    """
    with DDGS() as ddgs:
        results = ddgs.text(query, max_results=20)
        return {"results": results}


def submit_credentials(username: str, password: str):
    """
    Dummy function to simulate credential submission
    """

    logging.info("LLM submitted credentials %s:%s", username, password)
    return {"message": f"Credentials for {username} submitted successfully."}


if __name__ == "__main__":
    available_functions = {
        'get_date': get_date,
        'search_web': search_web,
        'fetch_url': fetch_url,
        'submit_credentials': submit_credentials,
    }

    messages = [{'role': 'user', 'content':
    """
    You are a blueteam pentester trying to find default credentials for a web application called "MIND: A simple self hosted reminder application".

    Follow these steps to find the credentials:
    1. Identify the official website or repository for the application.
    2. Crawl the site or repository for any documentation, installation guides, or configuration files that might contain default credentials. Follow links if necessary.
    3. Submit the found credentials using the submit_credentials tool.

    Search the web using carefully chosen, descriptive queries.
    Use the fetch_url tool to retrieve the content of promising links.
    If you find unrelated content, try refining your search.
    You may use tools multiple times. Do not give up quickly.
    Submit the credentials using the submit_credentials tool once you find them.
    """}]
    while True:
        response: ollama.ChatResponse = ollama.chat(
            model=MODEL,
            messages=messages,
            tools=available_functions.values(),
            think=True,
            stream=False,
        )
        messages.append(response.message)
        logging.info("Thinking: %s", response.message.thinking)
        logging.info("Content: %s", response.message.content)
        if response.message.tool_calls:
            for tc in response.message.tool_calls:
                if tc.function.name in available_functions:
                    logging.info("Calling %s with arguments %s", tc.function.name, tc.function.arguments)
                    result = available_functions[tc.function.name](**tc.function.arguments)
                    logging.info("Result: %s", result)
                    # add the tool result to the messages
                    messages.append({'role': 'tool', 'tool_name': tc.function.name, 'content': str(result)})
        else:
            # end the loop when there are no more tool calls
            break

    print("Done")
