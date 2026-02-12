"""
CredSearcher module. Takes keywords from the KeywordExtractor module and performs a web search
to find potential default credentials.
"""

import re
import time
import urllib.parse
import queue
import threading
from contextlib import contextmanager
from pathlib import Path
from threading import Thread, Event
import logging
from dataclasses import dataclass
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
import simhash
from pubsub import pub
from bs4 import BeautifulSoup
from markdownify import markdownify
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from scanner.ai.llm import get_chat_model
from scanner.ai.tools import make_credential_testing_tools
from scanner.db.models import Endpoint
from scanner.db import DBConnectionMixin
from scanner.settings import Settings


PROMPT_TEMPLATE = """
<<<PAGE CONTENT>>>
%s
<<<END PAGE CONTENT>>>
You are a blueteam pentester trying to test default credentials for a web application at "%s".
The login page has the HTML content above.
The default credentials you want to test are:
- Username: "%s"
- Password: "%s"

Follow these steps to test the credentials:
1. Identify required form fields.
2. Send keys to the from fields using css selectors and the insert_text_into_field tool.
3. Submit the form using the click_button tool. Then terminate without further output.

You may use tools multiple times. Do not give up quickly. ONLY CALL TOOLS ONE BY ONE.
After calling a tool, wait for the result before calling another tool.
"""

logger = logging.getLogger('scanner.cred_tester')

# set of messages that might indicate a login failure
NEGATIVE_MESSAGES = ["invalid username", "invalid password", "user does not exist",
                     "incorrect username", "incorrect password", "login failed",
                     "authentication failed", "invalid credentials", "wrong username"
                     "wrong password", "unable to log in", "user not found"
                     "username not found", "email not found", "password is incorrect",
                     "no account found with this username", "invalid email",
                     "login unsuccessful"]


@dataclass
class PageState:
    # relevant page state for comparison pre and post credential submission, to determine if login was successful
    url: str
    page_source: str
    title: str
    cookies: list[dict]

    def cleaned_page_source(self):
        return clean_page_source(self.page_source)

    def path(self, ignore_params=True):
        parts = urllib.parse.urlparse(self.url)
        if ignore_params:
            return parts.path
        if parts.query or parts.fragment:
            return f"{parts.path}?{parts.query}#{parts.fragment}"
        return parts.path

    def simhash(self):
        return md_simhash(self.page_source)

    def has_password_input(self):
        soup = BeautifulSoup(self.page_source, "html.parser")
        return bool(soup.select("input[type=password]"))

    def common_failure_messages(self, ignore=set()):
        md = markdownify(self.page_source).lower()
        return [msg for msg in NEGATIVE_MESSAGES if msg.lower() in md and msg not in ignore]

    def has_common_failure_messages(self, ignore=set()):
        return len(self.common_failure_messages(ignore)) > 0

    def __str__(self):
        return f"PageState(url={self.url}, title={self.title}, cookies={[c.get('name') for c in self.cookies]}, page_len={len(self.page_source)})"


def md_simhash(html: str) -> simhash.Simhash:
    """Computes the simhash of cleaned HTML content."""
    # TODO: evaluate other simhash techniques like tlsh
    md = markdownify(html)
    cleaned_md = re.sub(r'\s+', ' ', md)
    return simhash.Simhash(cleaned_md)

def clean_page_source(html: str) -> str:
    return str(cleaned_soup(html))

def cleaned_soup(html: str):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "video", "svg", "object", "embed", "iframe", "audio"]):
        tag.decompose()
    return soup


class CredTester(DBConnectionMixin, Thread):
    def __init__(self):
        super().__init__()
        self.termination_event = Event()
        self.cred_searcher_done_event = Event()
        self.failed_login_baselines = {}
        self.task_queue: queue.Queue[tuple[int, str, str] | None] = queue.Queue()
        self.in_flight: set[tuple[int, str, str]] = set()
        self.in_flight_lock = threading.Lock()
        self.max_workers = max(1, Settings().max_webdrivers)
        self.workers: list[Thread] = []
        pub.subscribe(self._on_abort, 'abort')
        pub.subscribe(self.cred_searcher_done_event.set, 'cred_searcher.done')

    def run_with_db(self):
        self.workers = [
            Thread(target=self._worker, name=f"cred-tester-{i}", daemon=True)
            for i in range(self.max_workers)
        ]
        for worker in self.workers:
            worker.start()

        while not self.termination_event.is_set():
            # aborts early for a service if any endpoint is found with working creds
            unresolved_login_panels: list[Endpoint] = [panel for panel in Endpoint.select()
                .where((Endpoint.is_login == True) & (Endpoint.working_credentials == ''))
                if len(panel.untested_credentials()) > 0 and not panel.service.endpoint_with_working_creds_found()
            ]

            for login_panel in unresolved_login_panels:
                for (username, password) in login_panel.untested_credentials():
                    key = (login_panel.pk, username, password)
                    with self.in_flight_lock:
                        if key in self.in_flight:
                            continue
                        self.in_flight.add(key)
                    self.task_queue.put(key)
            with self.in_flight_lock:
                in_flight_empty = not self.in_flight

            if (
                len(unresolved_login_panels) == 0
                and self.cred_searcher_done_event.is_set()
                and self.task_queue.empty()
                and in_flight_empty
            ):
                break

            self.termination_event.wait(2)

        self.termination_event.set()
        for _ in self.workers:
            self.task_queue.put(None)
        for worker in self.workers:
            worker.join()

        pub.sendMessage('cred_tester.done')
        logger.info("CredTester exited")

    def _worker(self):
        while not self.termination_event.is_set():
            try:
                item = self.task_queue.get(timeout=1)
            except queue.Empty:
                continue

            if item is None:
                break

            endpoint_id, username, password = item
            try:
                endpoint = Endpoint.get_by_id(endpoint_id)
                if endpoint.service.endpoint_with_working_creds_found():
                    continue
                self.test_credentials(endpoint, username, password)
            finally:
                with self.in_flight_lock:
                    self.in_flight.discard(item)
                self.task_queue.task_done()

    def _on_abort(self):
        self.termination_event.set()

    def run_baseline_test(self, endpoint: Endpoint) -> tuple[PageState, PageState]:
        """
        Runs a baseline test with known wrong credentials to establish a reference point for failed login attempts,
        to compare against when testing real credentials. Caches the result per endpoint to avoid redundant tests.
        """
        cached = self.failed_login_baselines.get(endpoint.pk)
        if cached:
            return cached

        # hardcoding to allow LLM response caching
        # should not be too long to avoid length-errors
        wrong_username = "invalid_user"
        wrong_password = "invalid_pass"
        logger.debug("Capturing failed-login baseline on %s", endpoint.url())
        baseline = self.run_llm_login(endpoint, wrong_username, wrong_password, attempt_label="baseline")

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

    def save_screenshot(self, driver, endpoint: Endpoint, username: str, password: str, attempt_label: str, phase: str):
        """Saves a screenshot of the current page state with a filename containing the endpoint, credentials, attempt label, and phase (before/after)."""
        screenshot_dir = self._get_screenshot_dir()
        if not screenshot_dir:
            return

        parts = urllib.parse.urlparse(endpoint.url())
        host = self._sanitize_for_filename(parts.hostname or "host")
        path = self._sanitize_for_filename(parts.path.strip("/") or "root")
        user = self._sanitize_for_filename(username)
        pwd = self._sanitize_for_filename(password)
        label = self._sanitize_for_filename(attempt_label)
        ts = int(time.time() * 1000)
        filename = f"endpoint-{endpoint.pk}_{host}_{path}_{label}_user-{user}_pass-{pwd}_{phase}_{ts}.png"
        driver.save_screenshot(str(screenshot_dir / filename))

    def record_page_state(self, driver) -> PageState:
        """Records relevant page state for comparison pre and post credential submission, to determine if login was successful."""
        return PageState(
            url=driver.current_url,
            page_source=driver.page_source,
            title=driver.title,
            cookies=driver.get_cookies()
        )

    def wait_for_element(self, driver, selector: str, timeout_seconds: int = 10):
        """Waits for an element matching the given CSS selector to be present in the DOM, up to a timeout."""
        try:
            WebDriverWait(driver, timeout_seconds).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, selector)
            )
        except TimeoutException:
            pass

    def visit_login_panel(self, driver, url: str) -> bool:
        """Navigates to the login panel URL and waits for it to load, handling potential host mismatches between the initial URL and the form action URL."""
        try:
            driver.get(url)
            self.wait_for_element(driver, "input[type=password], input[type=text], input[type=email]")
        except TimeoutException as exc:
            logger.warning("WebDriver navigation timed out for %s: %s", url, str(exc))
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            self.wait_for_element(driver, "input[type=password], input[type=text], input[type=email]", timeout_seconds=3)
            if driver.find_elements(By.CSS_SELECTOR, "input[type=password], input[type=text], input[type=email]"):
                return True
            return False
        except WebDriverException as exc:
            logger.warning("WebDriver navigation failed for %s: %s", url, str(exc))
            return False

        # Remove all script tags and their contents from the HTML source (to prevent overloading LLM)
        soup = cleaned_soup(driver.page_source)

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
                    try:
                        driver.get(action_url)
                        self.wait_for_element(driver, "input[type=password], input[type=text], input[type=email]")
                    except TimeoutException as exc:
                        logger.warning("WebDriver navigation timed out for %s: %s", action_url, str(exc))
                        try:
                            driver.execute_script("window.stop();")
                        except Exception:
                            pass
                        self.wait_for_element(driver, "input[type=password], input[type=text], input[type=email]", timeout_seconds=3)
                        if driver.find_elements(By.CSS_SELECTOR, "input[type=password], input[type=text], input[type=email]"):
                            return True
                        return False
                    except WebDriverException as exc:
                        logger.warning("WebDriver navigation failed for %s: %s", action_url, str(exc))
                        return False

        return True


    def run_llm_login(self, endpoint: Endpoint, username: str, password: str, attempt_label: str = "attempt") -> tuple[PageState, PageState]:
        """
        Performs a login attempt on the given endpoint with the given credentials, using the LLM to interact with the page.
        Returns the page state before and after the login attempt, for comparison to determine if the login was successful.
        """
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--allow-insecure-localhost")
        options.add_argument("--allow-running-insecure-content")
        options.page_load_strategy = "eager"

        with webdriver.Chrome(options=options) as driver:
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(30)

            if not self.visit_login_panel(driver, endpoint.url()):
                raise RuntimeError(f"Failed to load login panel: {endpoint.url()}")

            self.save_screenshot(driver, endpoint, username, password, attempt_label, "before")
            pre_login_state = self.record_page_state(driver)
            
            full_prompt = PROMPT_TEMPLATE % (pre_login_state.cleaned_page_source(), pre_login_state.url, username, password)
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

                # wait for potential redirects or DOM updates triggered by form submission
                try:
                    WebDriverWait(driver, 10).until(
                        lambda d: urllib.parse.urlparse(d.current_url).path != pre_login_state.path()
                        or d.page_source != pre_login_state.page_source
                    )
                except TimeoutException:
                    pass
            except WebDriverException as exc:
                logger.error("WebDriver failed during credential test for %s: %s", pre_login_state.url, str(exc))
                raise exc

            post_login_state = self.record_page_state(driver)
            self.save_screenshot(driver, endpoint, username, password, attempt_label, "after")

            return (pre_login_state, post_login_state)

    def test_credentials(self, endpoint: Endpoint, username: str, password: str):
        """
        Uses the LLM to test the given credentials on the given login panel endpoint.
        Success is determined by detecting a page change after submitting the login form.
        """
        try:
            logger.debug("Testing credentials %s:%s on %s", username, password, endpoint.url())

            baseline_pre_state, baseline_post_state = self.run_baseline_test(endpoint)
            pre_state, post_state = self.run_llm_login(endpoint, username, password, attempt_label="attempt")

            success_score = self.calculate_login_success_score(baseline_pre_state, baseline_post_state, pre_state, post_state)
            logger.debug("Calculated success score for credentials %s:%s on %s: %s", username, password, endpoint.url(), success_score)
            login_successful = success_score >= 20

            endpoint.add_tested_credentials((username, password))
            creds_str = f"{username}:{password}"
            if login_successful:
                logger.info("LOGIN SUCCESS on %s with creds %s", endpoint.url(), creds_str)
                endpoint.working_credentials = creds_str
                endpoint.save(only=[Endpoint.working_credentials])
            else:
                logger.info("LOGIN FAILURE on %s with creds %s", endpoint.url(), creds_str)

        except Exception as exc:
            logger.error("Error testing credentials %s:%s on %s: %s", username, password, endpoint.url(), str(exc))
            endpoint.add_tested_credentials((username, password))
        finally:
            endpoint.save(only=[Endpoint._tested_credentials])

    def calculate_login_success_score(self,  baseline_pre_state, baseline_post_state, pre_state, post_state):
        logger.debug("Testing credentials with states:\nBaseline pre-login: %s\nBaseline post-login: %s\nAttempt pre-login: %s\nAttempt post-login: %s",
                    baseline_pre_state,
                    baseline_post_state,
                    pre_state,
                    post_state
        )

        # Calculate a success score based on multiple signals comparing the attempt states to the baseline states,
        # to determine if the login was successful. This is more robust than relying on a single signal like simhash distance, which can be noisy.
        # All thresholds and weights are selected completely arbitrary with no reasoning whatsoever.
        # Ideally, a small ML model or something similar could be used.
        # TODO: if success is unclear, use LLM for final judgement
        success_score = 0

        # Part 1: if the simhash distance increased significantly compared to the baseline, it's a strong success signal
        baseline_simhash_distance = baseline_pre_state.simhash().distance(baseline_post_state.simhash())
        attempt_simhash_distance = pre_state.simhash().distance(post_state.simhash())
        logger.debug("Simhash distances - Baseline: %s, Attempt: %s", baseline_simhash_distance, attempt_simhash_distance)
        success_score += max(0, attempt_simhash_distance - baseline_simhash_distance) * 2

        # Part 2: if new cookies are set after the login attempt that were not set in the baseline failed login, it's a strong success signal
        baseline_post_cookies = {c.get("name") for c in baseline_post_state.cookies}
        attempt_post_cookies = {c.get("name") for c in post_state.cookies}
        if len(attempt_post_cookies - baseline_post_cookies) > 0:
            success_score += 15
        else:
            success_score -= 7

        # Part 3: if the title is different from both attempt pre-state and baseline post-state, it's a moderate success signal
        if post_state.title != pre_state.title and post_state.title != baseline_post_state.title:
            success_score += 7

        # Part 4: if the path is different from both attempt pre-state and baseline post-state, it's a moderate success signal
        if post_state.path() != pre_state.path() and post_state.path() != baseline_post_state.path():
            success_score += 7

        # Part 5: if there are no password inputs in the post-login page but there are in the baseline post-login, it's a moderate success signal
        if not post_state.has_password_input() and baseline_post_state.has_password_input():
            success_score += 7

        # Part 6: if the baseline post-login page has negative messages but the attempt post-login does not, that's another success signal
        ignore = set(pre_state.common_failure_messages()) | set(baseline_pre_state.common_failure_messages())
        if baseline_post_state.has_common_failure_messages(ignore) and not post_state.has_common_failure_messages(ignore):
            success_score += 7
        if post_state.has_common_failure_messages(ignore):
            success_score -= 7

        return success_score
