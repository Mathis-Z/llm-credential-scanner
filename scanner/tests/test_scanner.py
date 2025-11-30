import threading
import logging
from pubsub import pub
import scanner

class TestScanner(threading.Thread):
    def __init__(self, args):
        super().__init__()
        self.scanner_args = args
        self.detected_creds = []

    def run(self):
        pub.subscribe(self._on_credential_detected, 'creds_tester.successful_login')
        logging.debug("Running TestScanner with args: %s", self.scanner_args)
        scanner.main.run(self.scanner_args)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pub.sendMessage('abort')
        self.join()

    def _on_credential_detected(self, url, username, password):
        logging.info("TestScanner detected credentials: %s %s:%s", url, username, password)
        self.detected_creds.append((url, username, password))

    def finds_creds(self, url=None, username=None, password=None, timeout=300):
        waited = 0
        interval = 1
        while waited < timeout:
            for cred in self.detected_creds:
                url_match = (url is None or cred[0] == url)
                username_match = (username is None or cred[1] == username)
                password_match = (password is None or cred[2] == password)
                if url_match and username_match and password_match:
                    logging.info("TestScanner found matching credentials: %s", cred)
                    return True

            threading.Event().wait(interval)
            waited += interval
        return False
