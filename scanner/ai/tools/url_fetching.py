import logging
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.tools import tool
from markdownify import markdownify

from scanner.ai.llm import get_chat_model
from scanner.shared.fetching import fetch_url

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
