"""
CredSearcher module. Takes keywords from the KeywordExtractor module and performs a web search
to find potential default credentials.
"""

import re
import time
import urllib.parse
from pathlib import Path
from threading import Thread, Event
import logging
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
import simhash
from pubsub import pub
from bs4 import BeautifulSoup
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from scanner.ai.llm import get_chat_model
from scanner.ai.tools import make_credential_testing_tools
from scanner.db.models import Endpoint
from scanner.db import DBConnectionMixin
from scanner.settings import Settings


PROMPT_TEMPLATE = """
You are a blueteam pentester trying to test default credentials for a web application at "%s".
The default credentials you want to test are:
- Username: "%s"
- Password: "%s"

Follow these steps to test the credentials:
1. Identify required form fields.
2. Send keys to the from fields using css selectors and the insert_text_into_field tool.
3. Submit the form using the click_button tool. Then terminate without further output.

You may use tools multiple times. Do not give up quickly. ONLY CALL TOOLS ONE BY ONE.
After calling a tool, wait for the result before calling another tool.
The login page has the following HTML content:
<<<PAGE CONTENT>>>
%s
<<<END PAGE CONTENT>>>
"""

logger = logging.getLogger('scanner.cred_tester')

class CredTester(DBConnectionMixin, Thread):
    def __init__(self):
        super().__init__()
        self.termination_event = Event()
        self.cred_searcher_done_event = Event()
        self.failed_login_baselines = {}
        pub.subscribe(self._on_abort, 'abort')
        pub.subscribe(self.cred_searcher_done_event.set, 'cred_searcher.done')

    def run(self):
        while not self.termination_event.is_set():
            unresolved_login_panels: list[Endpoint] = list(
                Endpoint.select()
                .where((Endpoint.is_login == True) & (Endpoint.working_credentials == ''))
            )
            panels_with_untested_creds = [panel for panel in unresolved_login_panels if len(panel.untested_credentials()) > 0]

            if len(panels_with_untested_creds) == 0 and self.cred_searcher_done_event.is_set():
                break

            for login_panel in panels_with_untested_creds:
                for (username, password) in login_panel.untested_credentials():
                    self.test_credentials(login_panel, username, password)

            self.termination_event.wait(3)

        pub.sendMessage('cred_tester.done')
        logger.info("CredTester exited")

    def _on_abort(self):
        self.termination_event.set()

    # TODO: code duplication with webenum module
    def clean_html_for_simhash(self, html: str) -> str:
        """Cleans HTML content to improve simhash accuracy."""
        # Remove scripts and styles
        soup = BeautifulSoup(html, 'html.parser')
        for script_or_style in soup(['script', 'style', 'link']):
            script_or_style.decompose()
        text = soup.get_text()
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        return text

    def simhash(self, html: str) -> simhash.Simhash:
        """Computes the simhash of cleaned HTML content."""
        # TODO: evaluate other simhash techniques like tlsh
        # TODO: evaluate using just markdown content instead of full HTML
        cleaned_html = self.clean_html_for_simhash(html)
        return simhash.Simhash(cleaned_html)

    def _url_signature(self, url: str) -> str:
        parts = urllib.parse.urlparse(url)
        if parts.query or parts.fragment:
            return f"{parts.path}?{parts.query}#{parts.fragment}"
        return parts.path

    def _get_failed_login_baseline(self, endpoint: Endpoint):
        cached = self.failed_login_baselines.get(endpoint.pk)
        if cached:
            return cached

        wrong_username = f"invalid_user_{int(time.time())}"
        wrong_password = f"invalid_pass_{int(time.time())}"
        logger.debug("Capturing failed-login baseline on %s", endpoint.url())
        baseline = self._perform_login_attempt(endpoint, wrong_username, wrong_password, attempt_label="baseline")
        if baseline:
            self.failed_login_baselines[endpoint.pk] = baseline
        return baseline

    def _sanitize_for_filename(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "")
        return safe.strip("_-") or "na"

    def _get_screenshot_dir(self) -> Path | None:
        artifacts_dir = Settings().artifacts_dir
        if not artifacts_dir:
            return None
        path = Path(artifacts_dir) / "screenshots"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _save_screenshot(self, driver, endpoint: Endpoint, username: str, attempt_label: str, phase: str):
        screenshot_dir = self._get_screenshot_dir()
        if not screenshot_dir:
            return

        parts = urllib.parse.urlparse(endpoint.url())
        host = self._sanitize_for_filename(parts.hostname or "host")
        path = self._sanitize_for_filename(parts.path.strip("/") or "root")
        user = self._sanitize_for_filename(username)
        label = self._sanitize_for_filename(attempt_label)
        ts = int(time.time() * 1000)
        filename = f"endpoint-{endpoint.pk}_{host}_{path}_{label}_user-{user}_{phase}_{ts}.png"
        driver.save_screenshot(str(screenshot_dir / filename))

    def _perform_login_attempt(self, endpoint: Endpoint, username: str, password: str, attempt_label: str = "attempt"):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        driver = webdriver.Chrome(options=options)

        try:
            try:
                driver.get(endpoint.url())
            except WebDriverException as exc:
                logger.warning("WebDriver navigation failed for %s: %s", endpoint.url(), str(exc))
                return None

            # Remove all script tags and their contents from the HTML source (to prevent overloading LLM)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            for script in soup.find_all("script"):
                script.decompose()

            # If the form action host differs (localhost vs 127.0.0.1), re-open on the action host
            current_url = driver.current_url
            current_parts = urllib.parse.urlparse(current_url)
            form = soup.find("form")
            form_action = form.get("action") if form else None
            if form_action:
                action_url = urllib.parse.urljoin(current_url, form_action)
                action_parts = urllib.parse.urlparse(action_url)
                if action_parts.hostname and action_parts.hostname != current_parts.hostname:
                    host_pair = {action_parts.hostname, current_parts.hostname}
                    if host_pair == {"localhost", "127.0.0.1"} and action_parts.port == current_parts.port:
                        logger.debug(
                            "Form action host mismatch (current=%s action=%s). Re-opening on action host.",
                            current_url,
                            action_url,
                        )
                        driver.get(action_url)
                        soup = BeautifulSoup(driver.page_source, "html.parser")
                        for script in soup.find_all("script"):
                            script.decompose()

            self._save_screenshot(driver, endpoint, username, attempt_label, "before")

            # store page info to compare with after tool calls
            before_url = driver.current_url
            before_raw_page_source = driver.page_source
            before_page_source = str(soup)
            before_path = urllib.parse.urlparse(driver.current_url).path
            before_title = driver.title
            before_cookies = driver.get_cookies()
            before_has_password = bool(soup.select("input[type=password]"))
            logger.debug(
                "Before submit: url=%s path=%s title=%s cookies=%s page_len=%s",
                before_url,
                before_path,
                before_title,
                [c.get("name") for c in before_cookies],
                len(before_raw_page_source or "")
            )

            full_prompt = PROMPT_TEMPLATE % (endpoint.url(), username, password, before_page_source)
            llm = get_chat_model(reasoning=False)
            tools = make_credential_testing_tools(driver)
            agent = create_agent(llm, tools=tools)

            # https://docs.langchain.com/oss/python/langchain/agents#streaming
            try:
                for chunk in agent.stream({"messages": [{"role": "user", "content": full_prompt}]}, stream_mode="values"):
                    # Each chunk contains the full state at that point
                    latest_message = chunk["messages"][-1]

                    logger.debug("---------------------------- Chunk ----------------------------")
                    if isinstance(latest_message, ToolMessage):
                        logger.debug("Tool output: %s", latest_message.content)
                    elif isinstance(latest_message, HumanMessage):
                        logger.debug("User: %s", latest_message.content)
                    elif isinstance(latest_message, AIMessage):
                        if latest_message.tool_calls:
                            stringified_tool_calls = ", ".join(
                                [f"{tc['name']}({tc['args']})" for tc in latest_message.tool_calls]
                            )
                            logger.debug("AI: [Calling tools: %s]", stringified_tool_calls)
                        else:
                            logger.debug("AI: %s", latest_message.content)
            except WebDriverException as exc:
                logger.warning("WebDriver failed during credential test for %s: %s", endpoint.url(), str(exc))
                return None
            finally:
                # wait for potential redirects or DOM updates triggered by form submission
                try:
                    WebDriverWait(driver, 10).until(
                        lambda d: urllib.parse.urlparse(d.current_url).path != before_path
                        or d.page_source != before_raw_page_source
                    )
                except TimeoutException:
                    pass
                time.sleep(5)
                # to compare with before_page_source need to remove script tags again
                soup = BeautifulSoup(driver.page_source, "html.parser")
                for script in soup.find_all("script"):
                    script.decompose()
                after_page_source = str(soup)
                after_path = urllib.parse.urlparse(driver.current_url).path
                after_url = driver.current_url
                after_title = driver.title
                after_raw_page_source = driver.page_source
                after_cookies = driver.get_cookies()
                after_has_password = bool(soup.select("input[type=password]"))

            self._save_screenshot(driver, endpoint, username, attempt_label, "after")

            return {
                "before_url": before_url,
                "before_path": before_path,
                "before_title": before_title,
                "before_page_source": before_page_source,
                "before_raw_page_source": before_raw_page_source,
                "before_cookies": before_cookies,
                "before_has_password": before_has_password,
                "after_url": after_url,
                "after_url_sig": self._url_signature(after_url),
                "after_path": after_path,
                "after_title": after_title,
                "after_page_source": after_page_source,
                "after_raw_page_source": after_raw_page_source,
                "after_cookies": after_cookies,
                "after_has_password": after_has_password,
                "after_simhash": self.simhash(after_page_source),
            }
        finally:
            driver.quit()

    def test_credentials(self, endpoint: Endpoint, username: str, password: str):
        """
        Uses the LLM to test the given credentials on the given login panel endpoint.
        Success is determined by detecting a page change after submitting the login form.
        """
        try:
            logger.debug("Testing credentials %s:%s on %s", username, password, endpoint.url())

            baseline = self._get_failed_login_baseline(endpoint)
            attempt = self._perform_login_attempt(endpoint, username, password, attempt_label="attempt")
            if not attempt:
                endpoint.add_tested_credentials((username, password))
                endpoint.save()
                return

            before_cookie_names = {c.get("name") for c in attempt["before_cookies"]}
            after_cookie_names = {c.get("name") for c in attempt["after_cookies"]}
            logger.debug(
                "After submit: url=%s path=%s title=%s cookies=%s page_len=%s new_cookies=%s removed_cookies=%s",
                attempt["after_url"],
                attempt["after_path"],
                attempt["after_title"],
                [c.get("name") for c in attempt["after_cookies"]],
                len(attempt["after_raw_page_source"] or ""),
                sorted(after_cookie_names - before_cookie_names),
                sorted(before_cookie_names - after_cookie_names),
            )

            if baseline:
                baseline_distance = baseline["after_simhash"].distance(attempt["after_simhash"])
                baseline_cookie_names = {c.get("name") for c in baseline["after_cookies"]}
                attempt_cookie_names = {c.get("name") for c in attempt["after_cookies"]}
                cookie_name_delta = baseline_cookie_names != attempt_cookie_names
                title_changed = (baseline["after_title"] or "") != (attempt["after_title"] or "")
                url_changed = baseline.get("after_url_sig") != attempt["after_url_sig"]
                password_gone = baseline.get("after_has_password", True) and not attempt["after_has_password"]
                login_successful = (
                    (attempt["after_path"] != baseline["after_path"]) or
                    url_changed or
                    password_gone or
                    (baseline_distance > 7) or
                    title_changed or
                    cookie_name_delta
                )
                logger.debug(
                    "Baseline compare: baseline_path=%s attempt_path=%s simhash_distance=%s title_changed=%s cookie_name_delta=%s url_changed=%s password_gone=%s",
                    baseline["after_path"],
                    attempt["after_path"],
                    baseline_distance,
                    title_changed,
                    cookie_name_delta,
                    url_changed,
                    password_gone
                )
            else:
                simhash_distance = self.simhash(attempt["before_page_source"]).distance(attempt["after_simhash"])
                url_changed = self._url_signature(attempt["before_url"]) != attempt["after_url_sig"]
                password_gone = attempt.get("before_has_password", True) and not attempt["after_has_password"]
                login_successful = (
                    (attempt["before_path"] != attempt["after_path"]) or
                    url_changed or
                    password_gone or
                    (simhash_distance > 7) # experimental threshold
                )
                logger.debug(
                    "Login %s: before_path=%s after_path=%s simhash_distance=%s url_changed=%s password_gone=%s",
                    "successful" if login_successful else "failed",
                    attempt["before_path"],
                    attempt["after_path"],
                    simhash_distance,
                    url_changed,
                    password_gone
                )

            creds_str = f"{username}:{password}"
            if login_successful:
                logger.info("Found working credentials for %s: %s", endpoint.url(), creds_str)
                endpoint.working_credentials = creds_str
            else:
                logger.info("Credentials %s do not work on %s", creds_str, endpoint.url())
                endpoint.add_tested_credentials((username, password))

            endpoint.save()
        except Exception as exc:
            logger.error("Error testing credentials %s:%s on %s: %s", username, password, endpoint.url(), str(exc))
