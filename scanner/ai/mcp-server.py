from datetime import datetime
import logging
import requests
from mcp.server.fastmcp import FastMCP
from ddgs import DDGS


mcp = FastMCP("web_tools_server", json_response=True)

@mcp.tool()
def get_date():
    """
    Returns the current date and time.
    """
    return {"date": datetime.now().isoformat()}

@mcp.tool()
def search_web(query: str):
    """
    Perform a web search using DuckDuckGo library
    """
    with DDGS() as ddgs:
        results = ddgs.text(query, max_results=5)
        return {"results": results}

@mcp.tool()
def fetch_url(url: str):
    """
    Fetch URL content using requests
    """
    try:
        response = requests.get(url, timeout=10)
        return {"status": response.status_code, "content": response.text[:5000]}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def submit_credentials(input: dict):
    """
    Dummy function to simulate credential submission
    """
    username = input.get("username")
    password = input.get("password")

    logging.info("LLM submitted credentials %s:%s", username, password)
    return {"message": f"Credentials for {username} submitted successfully."}

# Run with streamable HTTP transport (e.g. used with agents)
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
