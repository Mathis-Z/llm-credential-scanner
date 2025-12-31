from typing import Any

from langchain.tools import tool
from selenium.webdriver.common.by import By


def make_credential_testing_tools(driver: Any):
    """Create LangChain tools bound to a shared Selenium WebDriver session.

    The returned tool callables close over the provided ``driver`` so the agent
    can reuse a single browser session across multiple tool calls.
    """
    @tool(description="Insert text into a field specified by a CSS selector in the shared browser session")
    def insert_text_into_field(selector: str, text: str) -> str:
        element = driver.find_element(By.CSS_SELECTOR, selector)
        try:
            element.clear()
            element.send_keys(text)
        except Exception as e:
            return f"error: {str(e)}"
        return "ok"

    @tool(description="Click a button specified by a CSS selector in the shared browser session")
    def click_button(selector: str) -> str:
        element = driver.find_element(By.CSS_SELECTOR, selector)
        try:
            element.click()
        except Exception as e:
            return f"error: {str(e)}"
        return "ok"

    return [insert_text_into_field, click_button]
