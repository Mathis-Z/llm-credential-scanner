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
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(elements) == 0:
                return "error: no elements found"
            if len(elements) > 1:
                logger.debug("Selector matched %d elements; using first", len(elements))
            element = elements[0]
            logger.debug(
                "Element info: tag=%s id=%s name=%s type=%s form_action=%s",
                element.tag_name,
                element.get_attribute("id"),
                element.get_attribute("name"),
                element.get_attribute("type"),
                element.get_attribute("formaction")
            )
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
            before_url = driver.current_url
            before_title = driver.title
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(elements) == 0:
                return "error: no elements found"
            if len(elements) > 1:
                logger.debug("Selector matched %d elements; using first", len(elements))
            element = elements[0]
            form = None
            try:
                form = element.find_element(By.XPATH, "ancestor::form[1]")
            except Exception:
                form = None
            logger.debug(
                "Element info: tag=%s id=%s name=%s type=%s form_action=%s form_method=%s",
                element.tag_name,
                element.get_attribute("id"),
                element.get_attribute("name"),
                element.get_attribute("type"),
                form.get_attribute("action") if form else None,
                form.get_attribute("method") if form else None,
            )
            element.click()
            time.sleep(1)
            logger.debug(
                "After click: url=%s title=%s (before url=%s title=%s)",
                driver.current_url,
                driver.title,
                before_url,
                before_title,
            )
        except Exception as e:
            return f"error: {str(e)}"
        return "ok"

    return [insert_text_into_field, click_button]
