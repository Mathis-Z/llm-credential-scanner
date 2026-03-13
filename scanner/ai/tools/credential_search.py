from ddgs import DDGS
from langchain.tools import tool


@tool(description="Perform a web search")
def search_web(query: str):
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
        return {"results": results}


@tool(description="Submit credentials (username & password)")
def submit_credentials(username: str, password: str):
    return {"message": f"Credentials for {username} submitted successfully."}
