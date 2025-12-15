import time
from seleniumbase import sb_cdp
from bs4 import BeautifulSoup
from langchain_community.llms.ollama import Ollama
from langchain_community.document_loaders import WebBaseLoader
from langchain_classic.chains.summarize import load_summarize_chain
import ollama


def wait_for_dom_settle(sb, timeout=2000, stable_ms=300):
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


def extract_text_and_links(page_source: str) -> str:
    soup = BeautifulSoup(page_source, 'html.parser')

    for tag in soup(['script', 'style', 'iframe', 'svg', 'img', 'link', 'noscript', 'meta']):
        tag.decompose()

    for tag in soup.find_all(True):
        if 'href' in tag.attrs:
            tag.attrs = {'href': tag.attrs['href']}
        else:
            tag.attrs = {}

    for _ in range(10):
        for tag in soup.find_all():
            if not tag.get_text(strip=True):
                tag.decompose()

#    for tag in soup.find_all(href=True):
#        tag.replace_with(f"[LINK: {tag['href']}]")

    return soup.prettify() # soup.get_text(separator='\n', strip=True)


def fetch_url(url: str):
    """
    Fetch a URL using SeleniumBase, renders JS, waits for the DOM to settle,
    and condenses it for useful content extraction.
    """
    try:
        sb = sb_cdp.Chrome(url=None, headless=False)
        sb.open(url)
        sb.sleep(1)  # Initial wait for page load
        wait_for_dom_settle(sb)
        content = sb.get_page_source()
        sb.driver.stop()
        return {"content": extract_text_and_links(content)}
    except Exception as e:
        return {"error": str(e)}


def summarize_url(url: str) -> str:
    loader = WebBaseLoader(url)
    docs = loader.load()

    llm = Ollama(model="qwen3:8B-Q4_K_M")

    # Build a Map-Reduce summarization chain
    chain = load_summarize_chain(
        llm,
        chain_type="map_reduce",
        verbose=True,
    )

    summary = chain.invoke(docs)
    return summary


def fetch_url_pretty(url: str):
    result = fetch_url(url)
    if "error" in result:
        return result
    content = result.get("content", "")

    messages = [{'role': 'user', 'content':
f"""
A blueteam pentester is browsing the web for default credentials of a web application.
The pentester has fetched a webpage. Please reduce the page content to the relevant information.
Include text content, links, and any credentials you might find. Also include context that might be necessary.
Do not add comments or explanations, just provide the condensed content. The page content is as follows:
{content}
"""
}]
    print("Sending content to LLM for condensation...")

    response: ollama.ChatResponse = ollama.chat(
        model="qwen3:8B-Q4_K_M",
        messages=messages,
        think=False,
    )

    return {"content": response.message.content}


if __name__ == "__main__":
    print(summarize_url("https://github.com/Casvt/MIND"))
    #with open("r.html", "w") as f:
    #    f.write(fetch_url("https://github.com/Casvt/MIND")["content"])
