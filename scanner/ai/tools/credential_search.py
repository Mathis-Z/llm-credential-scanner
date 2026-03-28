# LangChain tools for credential search via web search and URL fetching.

from ddgs import DDGS
from langchain.tools import tool


@tool(description="Perform a web search")
def search_web(query: str):
    """Search the web using DuckDuckGo and return top 5 results."""
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
        return {"results": results}
