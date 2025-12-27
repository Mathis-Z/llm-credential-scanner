from __future__ import annotations

import logging
from typing import Any

from langchain.tools import tool
from selenium.webdriver.common.by import By


def make_credential_testing_tools(driver: Any):
    """Create LangChain tools bound to a shared Selenium WebDriver session.

    The returned tool callables close over the provided ``driver`` so the agent
    can reuse a single browser session across multiple tool calls.
    """

    @tool(description="Get HTML content of the current page in the shared browser session")
    def get_login_html() -> str:
        return driver.page_source

    @tool(description="Insert text into a field specified by a CSS selector in the shared browser session")
    def insert_text_into_field(selector: str, text: str) -> str:
        element = driver.find_element(By.CSS_SELECTOR, selector)
        try:
            element.clear()
        except Exception:
            # Some elements (e.g., contenteditable) may not support clear().
            pass
        element.send_keys(text)
        return "ok"

    @tool(description="Click a button specified by a CSS selector in the shared browser session")
    def click_button(selector: str) -> str:
        element = driver.find_element(By.CSS_SELECTOR, selector)
        element.click()
        return "ok"

    return [get_login_html, insert_text_into_field, click_button]

@tool(description="Submit credentials (username & password) validity (true/false)")
def submit_credentials_validity(username: str, password: str, validity: bool):
    logging.info("LLM submitted credentials %s:%s with validity %s", username, password, validity)
    return {"message": f"Credentials for {username} submitted successfully with validity {validity}."}
