import time
import logging
from seleniumbase import SB
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.tools import tool
from markdownify import markdownify
import simhash

from scanner.ai.llm import get_chat_model

logger = logging.getLogger("scanner.ai.tools")

@tool(description="Fetch a URL, returning its summarized content.")
def fetch_url_summary(url: str) -> str:
    """
    Fetch a URL using SeleniumBase, renders JS, waits for the DOM to settle,
    and condenses it for useful content extraction.
    """
    _, raw_content = fetch_url(url)
    return summarize_text_with_map_reduce(raw_content)

@tool(description="Fetch a URL, returning its raw content as markdown.")
def fetch_url_as_markdown(url: str) -> str:
    """
    Fetch a URL using SeleniumBase, renders JS, waits for the DOM to settle,
    and returns the raw content.
    """
    _, raw_content = fetch_url(url)
    md = markdownify(raw_content)
    if len(md) > 20000:
        logger.warning("Fetched content from %s is very large (%i characters). Truncated to avoid LLM input error.", url, len(md))
        md = md[:20000] + "\n\n*Content truncated due to length.*"
    return md

def fetch_url(start_url: str) -> tuple[str, str]:
    """
    Fetch a URL using SeleniumBase, renders JS, waits for the DOM to settle,
    and returns the final URL and raw HTML content.
    """
    try:
        logger.debug("Fetching URL: %s", start_url)
        with SB(
            uc=True,
            headless=True,
            chromium_arg=[
                "--disable-dev-shm-usage",
                "--ignore-certificate-errors",
                "--allow-insecure-localhost",
                "--allow-running-insecure-content",
            ],
        ) as sb:
            sb.open(start_url)
            sb.sleep(1)  # Initial wait for page load
            _wait_for_dom_settle(sb)
            raw = sb.get_page_source()
            current_url = sb.get_current_url()
            return current_url, raw
    except Exception as e:
        logger.error("Failed to fetch URL %s via Chromium: %s", start_url, str(e))
        return start_url, ""


def _wait_for_dom_settle(sb, timeout_ms=2000, stable_ms=300):
    start = time.time()
    last_html = sb.get_page_source()

    while True:
        time.sleep(stable_ms / 1000)
        current_html = sb.get_page_source()

        if simhash.Simhash(current_html).distance(simhash.Simhash(last_html)) < 20:
            return
        logger.debug(simhash.Simhash(current_html).distance(simhash.Simhash(last_html)))

        last_html = current_html

        if (time.time() - start) * 1000 > timeout_ms:
            return


def summarize_text_with_map_reduce(
    text: str,
    map_prompt: str = "Summarize the following content concisely. Preserve key facts and technical details.",
    reduce_prompt: str = "Combine the following summaries into a single coherent summary. Remove redundancy and keep the most important points.",
    max_chunk_summary_tokens: int = 500,
    max_final_tokens: int = 500
) -> str:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=4000,
        chunk_overlap=300,
    )
    chunks = splitter.split_text(text)
    logger.info("Summarizing text of length %i, divided into %i chunks", len(text), len(chunks))
    logger.debug("Chunks: %s", chunks)

    summarised_chunks = [summarize_content_block(chunk, map_prompt, max_chunk_summary_tokens) for chunk in chunks]
    final_summary = reduce_summaries(summarised_chunks, reduce_prompt, max_final_tokens)

    return final_summary

def summarize_content_block(content: str, prompt: str, max_tokens: int = 500) -> str:
    llm = get_chat_model(reasoning=False)
    full_prompt = prompt + f"\n\n<<<BEGIN CONTENT>>>\n{content}\n<<<END CONTENT>>>\nEnsure the summary is no more than {max_tokens} tokens."
    response = llm.invoke([("human", full_prompt)])
    return response.content


def reduce_summaries(summaries: list[str], prompt: str, max_tokens: int = 500) -> str:
    llm = get_chat_model(reasoning=False)
    combined = "\n\n".join(summaries)
    prompt = prompt + f"\n\n<<<BEGIN SUMMARIES>>>\n{combined}\n<<<END SUMMARIES>>>\nEnsure the final summary is no more than {max_tokens} tokens."
    response = llm.invoke([("human", prompt)])
    return response.content
