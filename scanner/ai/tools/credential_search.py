import logging

from ddgs import DDGS
from langchain.tools import tool


@tool(description="Perform a web search")
def search_web(query: str):
    with DDGS() as ddgs:
        return {"results": ddgs.text(query, max_results=5)}


@tool(description="Submit credentials (username & password)")
def submit_credentials(username: str, password: str):
    logging.info("LLM submitted credentials %s:%s", username, password)
    return {"message": f"Credentials for {username} submitted successfully."}
