from scanner.tests.startup_script import StartupScript
from .test_scanner import TestScanner


def test_mind():
    with StartupScript("/scanner/tests/apps/mind.sh", "MIND running on"):
        with TestScanner(["localhost"]) as scanner:
            assert scanner.finds_creds(username="admin", password="admin")
