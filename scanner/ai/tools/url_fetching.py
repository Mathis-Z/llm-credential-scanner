# Fetches and converts web content to markdown via pooled browsers.

import logging
from markdownify import markdownify

from scanner.shared.fetching import fetch_url_with_browser, fetch_urls_with_browser

logger = logging.getLogger("scanner.ai.tools")


def fetch_url_as_markdown(url: str, truncate=True) -> str:
    """
    Fetch URL using browser, render JavaScript, wait for DOM to settle,
    and return raw HTML converted to markdown.
    """
    _, raw_content = fetch_url_with_browser(url)
    return _to_markdown(url, raw_content, truncate)


def fetch_urls_as_markdown(urls: list[str], truncate: bool = True) -> list[str | None]:
    """
    Fetch multiple URLs in parallel (via fetch_urls_with_browser) and convert each to markdown.

    Failed fetches are None in the corresponding position; results are in the
    same order as the input URLs.
    """
    results = fetch_urls_with_browser(urls)
    return [
        _to_markdown(url, result[1], truncate) if result is not None else None
        for url, result in zip(urls, results)
    ]


def _to_markdown(url: str, raw_content: str, truncate: bool) -> str:
    # Drop <img> tags entirely (rather than converting them to markdown image syntax) -
    # embedded/data-URI images have no whitespace to split on and break RAG chunking.
    md = markdownify(raw_content, strip=['img'])
    if truncate and len(md) > 32000:
        logger.warning("Fetched content from %s is very large (%i characters). Truncated to avoid LLM input error.", url, len(md))
        md = md[:32000] + "\n\n*Content truncated due to length.*"
    return md
