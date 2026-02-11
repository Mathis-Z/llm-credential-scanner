import time
import logging
from typing import Any

from langchain.tools import tool
from selenium.webdriver.common.by import By

logger = logging.getLogger('scanner.cred_tester.tools')

def _format_html_element(element) -> str:
    """Format a Selenium WebElement for logging, showing tag and key attributes."""
    try:
        outer_html = element.get_attribute('outerHTML')
        # Extract just the opening tag by finding the first '>'
        if '>' in outer_html:
            # Find the opening tag
            first_tag_end = outer_html.index('>')
            # Check if it's a self-closing tag
            if outer_html[first_tag_end-1] == '/':
                opening_tag = outer_html[:first_tag_end+1]
            else:
                # For non-self-closing tags, extract just the opening tag
                opening_tag = outer_html[:first_tag_end+1]
                # Add closing tag
                tag_name = element.tag_name
                opening_tag = f"{opening_tag}...</{tag_name}>"
        else:
            opening_tag = outer_html

        return opening_tag
    except Exception as e:
        logger.debug("Failed to format HTML element: %s", str(e))
        return f"<{element.tag_name} ...>"

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
                return "Error: No elements found"
            if len(elements) > 1:
                formatted_elements = "\n".join([_format_html_element(el) for el in elements])
                return "Error: Selector matched multiple elements:\n" + formatted_elements

            element = elements[0]
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
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(elements) == 0:
                return "error: no elements found"
            if len(elements) > 1:
                formatted_elements = "\n".join([_format_html_element(el) for el in elements])
                return "Error: Selector matched multiple elements:\n" + formatted_elements

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
        except Exception as e:
            return f"error: {str(e)}"
        return "ok"

    return [insert_text_into_field, click_button]
