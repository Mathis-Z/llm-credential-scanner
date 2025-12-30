import threading
import logging
import os
import time
from pubsub import pub
from selenium import webdriver
from selenium.webdriver.common.by import By

logger = logging.getLogger('scanner.creds_tester')

class CredsTester(threading.Thread):
    def __init__(self, max_webdrivers=3):
        super().__init__()
        self.webenum_done = False
        self.workers = []
        self.webdriver_semaphore = threading.Semaphore(max_webdrivers)
        pub.subscribe(self.on_webenum_done, 'webenum.done')
        pub.subscribe(self.on_login_panel_found, 'webenum_login_panel_found')
        pub.subscribe(self.on_webenum_done, 'abort')

    def run(self):
        while not self.webenum_done:
            threading.Event().wait(1)

        for worker in self.workers:
            worker.join()
        logger.info("CredsTester done.")

    def on_webenum_done(self):
        self.webenum_done = True

    def on_login_panel_found(self, url):
        script_dir = os.path.dirname(__file__)
        creds_abs_path = os.path.join(script_dir, 'generic_creds.txt')

        with open(creds_abs_path, 'r', encoding='utf-8') as creds_file:
            creds = [line.strip().split(':', 1) for line in creds_file.readlines() if ':' in line]

        worker = CredsTesterWorker(url, creds)
        worker.start()
        self.workers.append(worker)


class CredsTesterWorker(threading.Thread):
    def __init__(self, url, creds, webdriver_semaphore=None):
        super().__init__()
        self.url = url
        self.creds = creds
        self.webdriver_semaphore = webdriver_semaphore

    def run(self):
        for user, password in self.creds:
            try:
                if self.test_creds(user, password):
                    logger.info("Successful login on %s with %s:%s", self.url, user, password)
                    pub.sendMessage('creds_tester.successful_login', url=self.url, username=user, password=password)
                    return
            except Exception as e:
                logger.error("Error testing credentials on %s with %s:%s - %s", self.url, user, password, str(e))

    def find_username_input(self, driver):
        return driver.find_element(
            By.XPATH,
            "//input[translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='username']"
        )

    def find_password_input(self, driver):
        return driver.find_element(
            By.XPATH,
            "//input[translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='password']"
        )

    def find_login_button(self, driver):
        return driver.find_element(
            By.XPATH,
            "//button[@type='submit' or translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='login']"
        )

    def test_creds(self, user, password):
        if self.webdriver_semaphore:
            self.webdriver_semaphore.acquire()

        options = webdriver.FirefoxOptions()
        options.add_argument('--headless')
        driver = webdriver.Firefox(options=options)
        driver.get(self.url)

        username_input = self.find_username_input(driver)
        username_input.clear()
        username_input.send_keys(user)

        password_input = self.find_password_input(driver)
        password_input.clear()
        password_input.send_keys(password)

        old_url = driver.current_url
        submit_btn = self.find_login_button(driver)
        submit_btn.click()

        time.sleep(3)

        success = self.login_successful(driver, old_url)
        driver.close()

        if self.webdriver_semaphore:
            self.webdriver_semaphore.release()

        return success

    def login_successful(self, driver, old_url):
        if driver.current_url != old_url:
            return True

        logged_in_markers = [
            "//a[contains(., 'Logout')]",
            "//a[contains(., 'Sign out')]",
            "//button[contains(., 'Logout')]",
            "//button[contains(., 'Sign out')]",
            "//img[contains(@alt, 'profile') or contains(@class, 'avatar')]"
        ]

        for xp in logged_in_markers:
            if driver.find_elements(By.XPATH, xp):
                return True

        failure_markers = [
            "//div[contains(text(),'Invalid')]",
            "//div[contains(text(),'incorrect')]",
            "//div[contains(text(),'wrong password')]",
        ]

        for xp in failure_markers:
            if driver.find_elements(By.XPATH, xp):
                return False

        return None  # unknown
