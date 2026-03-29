# LangChain tools for LLM-driven credential testing via Selenium browser automation.

import time
import logging
from typing import Any

from langchain.tools import tool
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException

logger = logging.getLogger('scanner.cred_tester.tools')

def _format_html_element(element) -> str:
    """Format WebElement for logging, showing tag and key attributes only."""
    try:
        outer_html = element.get_attribute('outerHTML')
        if '>' in outer_html:
            first_tag_end = outer_html.index('>')
            # Check for self-closing tag
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
    """
    Create LangChain tools for browser automation in credential testing.
    
    Tools interact with a shared Selenium WebDriver session to:
    - insert_text_into_field: Fill form fields with credentials
    - click_button: Submit forms by clicking buttons
    """
    def _prepare_element(element) -> None:
        """Scroll element into view and focus it before interaction."""
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                element,
            )
            time.sleep(0.2)
        except Exception as exc:
            logger.debug("Failed to scroll element into view: %s", exc)

        try:
            if element.is_displayed() and element.is_enabled():
                element.click()
        except Exception as exc:
            logger.debug("Failed to focus element before input: %s", exc)

    @tool(description="Insert text into a field specified by a CSS selector in the shared browser session")
    def insert_text_into_field(selector: str, text: str) -> str:
        """Fill a form field with text, handling React/Vue-style inputs via JS fallback."""
        logger.debug("Inserting text into field with selector: %s", selector)
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(elements) == 0:
                page_source = driver.page_source
                return "Error: No elements found. The current page source is: <<<PAGE CONTENT>>>\n" + page_source + "\n<<<END PAGE CONTENT>>>"
            if len(elements) > 1:
                formatted_elements = "\n".join([_format_html_element(el) for el in elements])
                return "Error: Selector matched multiple elements:\n" + formatted_elements

            element = elements[0]
            _prepare_element(element)
            # Try standard send_keys first, fall back to JS injection for React/Vue inputs
            try:
                element.clear()
                element.send_keys(text)
            except Exception:
                driver.execute_script("arguments[0].value = '';", element)
                driver.execute_script("arguments[0].value = arguments[1];", element, text)
                driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", element)
                driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)
        except Exception as e:
            return f"error: {str(e)}"
        return "ok"

    @tool(description="Click a button specified by a CSS selector in the shared browser session")
    def click_button(selector: str) -> str:
        """Click a button or submit a form. Includes retry for stale elements and JS fallback."""
        time.sleep(2)
        logger.debug("Clicking button with selector: %s", selector)
        try:
            element = None
            for attempt in range(2):
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if len(elements) == 0:
                    page_source = driver.page_source
                    return "Error: No elements found. The current page source is: <<<PAGE CONTENT>>>\n" + page_source + "\n<<<END PAGE CONTENT>>>"
                if len(elements) > 1:
                    formatted_elements = "\n".join([_format_html_element(el) for el in elements])
                    return "Error: Selector matched multiple elements:\n" + formatted_elements

                element = elements[0]
                try:
                    _prepare_element(element)
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
                    try:
                        element.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", element)
                    break
                except StaleElementReferenceException:
                    if attempt == 0:
                        time.sleep(0.2)
                        continue
                    raise
            time.sleep(1)
        except Exception as e:
            try:
                # Final fallback: use JS to find and click element
                driver.execute_script(
                    "var el = document.querySelector(arguments[0]);"
                    "if (el) {"
                    "  if (el.form) { el.form.submit(); return; }"
                    "  el.click();"
                    "}",
                    selector,
                )
                time.sleep(1)
                return "ok"
            except Exception as exc:
                return f"error: {str(exc)}"
            return f"error: {str(e)}"
        return "ok"

    return [insert_text_into_field, click_button]
