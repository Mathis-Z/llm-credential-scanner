import time
import logging
from typing import Any

from langchain.tools import tool
from selenium.webdriver.common.by import By

logger = logging.getLogger('scanner.cred_tester.tools')

def make_credential_testing_tools(driver: Any):
    """Create LangChain tools bound to a shared Selenium WebDriver session.

    The returned tool callables close over the provided ``driver`` so the agent
    can reuse a single browser session across multiple tool calls.
    """
    @tool(description="Insert text into a field specified by a CSS selector in the shared browser session")
    def insert_text_into_field(selector: str, text: str) -> str:
        logger.debug("Inserting text into field with selector: %s", selector)
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
            element.clear()
            element.send_keys(text)
        except Exception as e:
            return f"error: {str(e)}"
        return "ok"

    @tool(description="Click a button specified by a CSS selector in the shared browser session")
    def click_button(selector: str) -> str:
        time.sleep(2)
        logger.debug("Clicking button with selector: %s", selector)
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
            element.click()
        except Exception as e:
            return f"error: {str(e)}"
        return "ok"

    return [insert_text_into_field, click_button]
