import requests
from mcp.server.fastmcp import FastMCP
from ddgs import DDGS

# Create MCP server instance
mcp = FastMCP("web_tools_server", json_response=True)

# Tools
@mcp.tool()
def get_date():
    """
    Returns the current date and time.
    """
    from datetime import datetime
    return {"date": datetime.now().isoformat()}

@mcp.tool()
def search_web(input: str):
    """
    Perform a web search using DuckDuckGo library
    """
    with DDGS() as ddgs:
        results = ddgs.text(input, max_results=5)
        return {"results": results}

@mcp.tool()
def fetch_url(input: str):
    """
    Fetch URL content using requests
    """
    try:
        response = requests.get(input, timeout=10)
        return {"status": response.status_code, "content": response.text[:5000]}
    except Exception as e:
        return {"error": str(e)}

# Run with streamable HTTP transport (e.g. used with agents)
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
