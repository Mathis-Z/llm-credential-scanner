from scanner.tests.startup_script import StartupScript
from .test_scanner import TestScanner


def test_mind():
    with StartupScript("/scanner/tests/apps/mind.sh", "MIND running on"):
        with TestScanner(["localhost"]) as scanner:
            assert scanner.finds_creds(username="admin", password="admin")

def test_mailcow():
    with StartupScript("/scanner/tests/apps/mailcow.sh", "Nginx health level: 100%"):
        with TestScanner(["localhost"]) as scanner:
            assert scanner.finds_creds(username="admin", password="moohoo")
