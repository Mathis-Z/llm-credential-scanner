import subprocess
import random
import logging
import time
from pathlib import Path
from dataclasses import dataclass
from tabulate import tabulate
import click
from scanner.tests.startup_script import RunDockerCompose
from scanner.db import Endpoint, Service, init_db
from scanner.settings import Settings
from scanner.main import configure_logging

KEEP_DB_FILES = True
logger = logging.getLogger("scanner.tests")


@dataclass
class TestResult:
    found_creds: bool
    verified_creds: bool
    found_login_panel: bool
    endpoints_num: int
    db_path: str = ""
    artifacts_dir: str = ""


class TemporaryScanArtifacts:
    def __init__(self):
        scan_id = random.randint(100000, 999999)
        self.dir_path = Path("/tmp/scanner_logs") / f"scanner-test-{scan_id}"
        self.db_path = self.dir_path / "scanner.db"
        self.scanner_log_path = self.dir_path / "scanner.log"
        self.docker_log_path = self.dir_path / "docker.log"

    def __enter__(self):
        self.dir_path.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if not KEEP_DB_FILES:
            self.db_path.unlink(missing_ok=True)
            self.scanner_log_path.unlink(missing_ok=True)
            self.docker_log_path.unlink(missing_ok=True)
            try:
                self.dir_path.rmdir()
            except OSError:
                pass


def found_creds(username, password):
    for s in Service.select():
        print(f"Checking service {s}")
        # s.credentials may be stored as list of lists (JSON) or tuples; compare values robustly
        for u, p in (s.credentials or []):
            if u == username and p == password:
                return True
    return False

def verified_creds(path, username, password):
    if path and path != "*":
        e = Endpoint.get_or_none((Endpoint.path == path) & (Endpoint.working_credentials == f"{username}:{password}"))
    else:
        e = Endpoint.get_or_none(Endpoint.working_credentials == f"{username}:{password}")
    return e is not None

def found_login_panel(path):
    if path and path != "*":
        e = Endpoint.get_or_none((Endpoint.path == path) & (Endpoint.is_login == True))
    else:
        e = Endpoint.get_or_none(Endpoint.is_login == True)
    return e is not None

def endpoints_num():
    return Endpoint.select().count()


def print_results(results: dict[str, TestResult | None]):
    """Prints the test results in a tabular format."""
    headers = [
        "Service Name",
        "Found Credentials",
        "Verified Credentials",
        "Found Login Panel",
        "Endpoints Detected",
        "DB Path",
        "Artifacts Dir"
    ]
    table = []

    for service_name, result in results.items():
        if result is None:
            table.append([service_name, "-", "-", "-", "-", "-", "-"])
            continue

        table.append([
            service_name,
            emojify(result.found_creds),
            emojify(result.verified_creds),
            emojify(result.found_login_panel),
            result.endpoints_num,
            result.db_path,
            result.artifacts_dir
        ])

    print(tabulate(table, headers=headers, tablefmt="grid"))

def emojify(value: bool):
    return "✅" if value else "❌"

def run_scanner(port, log_path, artifacts_dir, extra_args=[]):
    cmd = [
        "python",
        "-m",
        "scanner.main",
        "127.0.0.1",
        "-p",
        str(port),
        "-L",
        "DEBUG",
        "--log-file",
        str(log_path),
        "--artifacts-dir",
        str(artifacts_dir)
    ] + extra_args
    p = subprocess.Popen(cmd, text=True)
    p.wait()


def run_app_test(app_dir_name, port, login_path, username, password) -> TestResult:
    with TemporaryScanArtifacts() as artifacts:
        wait_path = "/" if login_path == "*" else login_path
        with RunDockerCompose(
            app_dir_name,
            wait_for_login_url=f"http://127.0.0.1:{port}{wait_path}",
            log_path=artifacts.docker_log_path
        ):
            run_scanner(
                port,
                artifacts.scanner_log_path,
                artifacts.dir_path,
                extra_args=["--db-path", str(artifacts.db_path)]
            )
            # Rebind our ORM to the same temporary DB used by the scanner run
            Settings().configure_cli_arguments(db_path=str(artifacts.db_path))
            init_db()
            r = TestResult(
                found_creds=found_creds(username, password),
                verified_creds=verified_creds(login_path, username, password),
                found_login_panel=found_login_panel(login_path),
                endpoints_num=endpoints_num(),
                db_path=str(artifacts.db_path),
                artifacts_dir=str(artifacts.dir_path)
            )
            return r

@click.command()
@click.option("--keep", is_flag=True, help="Keep temporary artifacts after tests complete")
@click.option("--select", "-s", default=None, help="Run test for a specific application only; comma-separated list; case-sensitive")
@click.option("--log-level", "-L", default="DEBUG", help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
def run(keep, select, log_level):
    configure_logging(log_level)
    start_time = time.time()
    init_db()
    global KEEP_DB_FILES
    KEEP_DB_FILES = keep or KEEP_DB_FILES

    if select:
        selected_apps = set([app.strip() for app in select.split(",")])

    test_cases = [
        ("4gaBoards", 3000, "/login", "demo", "demo"),
        ("BabyBuddy", 8000, "/login/", "admin", "admin"),
        ("BookStack", 6875, "/login", "admin@admin.com", "password"),
        ("CalibrWeb", 8083, "/login", "admin", "admin123"),
        ("ClipCascade", 8088, "/login", "admin", "admin123"),
        ("Convertigo", 28080, "/convertigo/admin/login.html", "admin", "admin"),
        # ("DataLens", 8080, "/auth/signin", "admin", "admin"), Worked, but is broken for some reason now
        ("DockerSSOServer", 3000, "/login", "username", "password"),
        ("Filadex", 8080, "/login", "admin", "admin"),
        ("Grafana", 3000, "/login", "admin", "admin"),
        ("Joplin", 22300, "/login", "admin@localhost", "admin"),
        # ("MongoExpress", 8081, "/", "admin", "pass"), WARNING: MongoDB 5.0+ requires a CPU with AVX support, and your current system does not appear to have that!
        ("osTicket", 8080, "/scp/login.php", "ostadmin", "Admin1"),
        ("ownCloud", 8080, "/login", "admin", "admin"),
        ("PasswordCockpit", 8080, "/login", "admin", "Admin123!"),
        ("Pyload", 8000, "/login", "admin", "password"),
        # ("Rainloop", 80, "/", "admin", "12345"), Error response from daemon: error while creating mount source path '/opt/docker-rainloop/data': mkdir /opt/docker-rainloop: read-only file system
        ("Readmine", 8084, "/login", "admin", "admin"),
        ("SonarQube", 9000, "/sessions/new", "admin", "admin"),
        ("Zabbix", 80, "*", "Admin", "zabbix")
    ]

    if select:
        test_cases = [tc for tc in test_cases if tc[0] in selected_apps]

    results: dict[str, TestResult | None] = {}
    for (app_name, port, login_path, username, password) in test_cases:
        try:
            results[app_name] = run_app_test(app_name, port, login_path, username, password)
        except Exception as exc:
            logger.error("Test for %s failed: %s", app_name, exc)
            results[app_name] = None

    print_results(results)
    logger.info("All tests completed in %.2f seconds.", time.time() - start_time)

if __name__ == "__main__":
    run()  # pylint: disable=no-value-for-parameter
