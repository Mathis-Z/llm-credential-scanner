# LangChain tools for fetching and summarizing web content via pooled browsers.

import logging
from langchain.tools import tool
from markdownify import markdownify

from scanner.shared.fetching import fetch_url_with_browser

logger = logging.getLogger("scanner.ai.tools")


@tool(description="Fetch a URL, returning its raw content as markdown.")
def fetch_url_as_markdown(url: str) -> str:
    """
    Fetch URL using browser, render JavaScript, wait for DOM to settle,
    and return raw HTML converted to markdown.
    """
    _, raw_content = fetch_url_with_browser(url)
    md = markdownify(raw_content)
    if len(md) > 32000:
        logger.warning("Fetched content from %s is very large (%i characters). Truncated to avoid LLM input error.", url, len(md))
        md = md[:32000] + "\n\n*Content truncated due to length.*"
    return md
