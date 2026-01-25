import time
import logging
from seleniumbase import sb_cdp
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.tools import tool
from markdownify import markdownify

from scanner.ai.llm import get_chat_model

logger = logging.getLogger("scanner.ai.tools")

@tool(description="Fetch a URL, returning its summarized content.")
def fetch_url_summary(url: str) -> str:
    """
    Fetch a URL using SeleniumBase, renders JS, waits for the DOM to settle,
    and condenses it for useful content extraction.
    """
    raw = _fetch_url(url)
    return summarize_text_with_map_reduce(raw)

@tool(description="Fetch a URL, returning its raw content.")
def fetch_url(url: str) -> str:
    """
    Fetch a URL using SeleniumBase, renders JS, waits for the DOM to settle,
    and returns the raw content.
    """
    return _fetch_url(url)

def _fetch_url(url: str) -> str:
    """
    Fetch a URL using SeleniumBase, renders JS, waits for the DOM to settle,
    and condenses it for useful content extraction.
    """
    try:
        sb = sb_cdp.Chrome(url=None, headless=True)
        sb.open(url)
        sb.sleep(1)  # Initial wait for page load
        _wait_for_dom_settle(sb)
        content = sb.get_page_source()
        sb.driver.stop()
        md = markdownify(content)
        if len(md) > 20000:
            logger.warning("Fetched content from %s is very large (%i characters). Truncated to avoid LLM input error.", url, len(md))
            md = md[:20000] + "\n\n*Content truncated due to length.*"
        return md
    except Exception as e:
        return str(e)


def _wait_for_dom_settle(sb, timeout=2000, stable_ms=300):
    start = time.time()
    last_html = sb.get_page_source()

    while True:
        time.sleep(stable_ms / 1000)
        current_html = sb.get_page_source()

        if current_html == last_html:
            return

        last_html = current_html

        if (time.time() - start) * 1000 > timeout:
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


if __name__ == "__main__":
    raw = _fetch_url("https://github.com/Casvt/MIND")
    print(summarize_text_with_map_reduce(raw))
