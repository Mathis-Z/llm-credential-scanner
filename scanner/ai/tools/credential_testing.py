from langchain.tools import tool


@tool(description="Get HTML content of the login page")
def get_login_html():
    return "work in progress"

@tool(description="Insert text into a field specified by a CSS selector")
def insert_text_into_field(selector: str, text: str):
    return "work in progress"

@tool(description="Click a button specified by a CSS selector")
def click_button(selector: str):
    return "work in progress"
