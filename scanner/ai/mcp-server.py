from datetime import datetime
import logging
import requests
from mcp.server.fastmcp import FastMCP
from ddgs import DDGS


mcp = FastMCP("web_tools_server", json_response=True)

@mcp.tool(
    name="get_date",
    description="Return the current date and time",
    meta={"tags": ["credential_search"]}
)
def get_date():
    return {"date": datetime.now().isoformat()}

@mcp.tool(
    name="search_web",
    description="Perform a web search",
    meta={"tags": ["credential_search"]}
)
def search_web(query: str):
    with DDGS() as ddgs:
        return {"results": ddgs.text(query, max_results=5)}

@mcp.tool(
    name="fetch_url",
    description="Fetch URL content",
    meta={"tags": ["credential_search"]}
)
def fetch_url(url: str):
    try:
        r = requests.get(url, timeout=10)
        return {"status": r.status_code, "content": r.text[:5000]}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool(
    name="submit_credentials",
    description="Submit credentials",
    meta={"tags": ["credential_search"]}
)
def submit_credentials(input: dict):
    username = input.get("username")
    password = input.get("password")
    logging.info("LLM submitted credentials %s:%s", username, password)
    return {"message": f"Credentials for {username} submitted successfully."}

@mcp.tool(
    name="get_login_html",
    description="Get HTML content of the login page",
    meta={"tags": ["credential_testing"]}
)
def get_login_html():
    return "work in progress"

@mcp.tool(
    name="insert_text_into_field",
    description="Insert text into a field specified by a CSS selector",
    meta={"tags": ["credential_testing"]}
)
def insert_text_into_field(selector: str, text: str):
    return "work in progress"

@mcp.tool(
    name="click_button",
    description="Click a button specified by a CSS selector",
    meta={"tags": ["credential_testing"]}
)
def click_button(selector: str):
    return "work in progress"


# Run with streamable HTTP transport (e.g. used with agents)
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
