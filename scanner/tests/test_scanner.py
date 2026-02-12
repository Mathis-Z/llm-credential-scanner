import logging
import scanner.main
from pubsub import pub
from scanner.db import DBConnectionMixin
from scanner.db.models import Endpoint

# TODO: run scanner in separate process to allow killing it
class TestScanner(DBConnectionMixin):
    def __init__(self, args):
        super().__init__()
        self.scanner_args = args
        self.run()

    def run_with_db(self):
        logging.debug("Running TestScanner with args: %s", self.scanner_args)
        scanner.main.run(
            args=self.scanner_args,
            standalone_mode=False
        )
