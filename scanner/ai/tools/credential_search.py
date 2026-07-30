# Web search via DuckDuckGo, used directly (non-agentically) by CredSearcher's RAG pipeline.

from ddgs import DDGS


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search the web using DuckDuckGo. Each result dict has 'title', 'href', 'body'."""
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))
