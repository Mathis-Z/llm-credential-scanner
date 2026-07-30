# Integration test suite for the scanner against real web applications.

import subprocess
import random
import logging
import time
from pathlib import Path
from dataclasses import dataclass
from tabulate import tabulate
import click
from scanner.tests.startup_script import RunDockerCompose
from scanner.db import Endpoint, Service, load_db, load_or_create_db
from scanner.db.models import DEFAULT_CREDS
from scanner.settings import override_settings
from scanner.main import configure_logging

KEEP_DB_FILES = True
logger = logging.getLogger("scanner.tests")


@dataclass
class TestResult:
    """Results from testing a single application deployment."""
    found_creds: bool | None
    verified_creds: bool | None
    verified_no_other_creds: bool | None
    found_login_panel: bool | None
    endpoints_num: int
    artifacts_dir: str = ""
    creds_are_trivial: bool = False


class TemporaryScanArtifacts:
    """
    Creates temporary directory for test artifacts (DB, logs).
    
    Automatically cleans up unless KEEP_DB_FILES is set.
    """
    def __init__(self):
        scan_id = random.randint(100000, 999999)
        self.dir_path = Path("/tmp/scan_artifacts") / f"scanner-test-{scan_id}"
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
    """Check if the given credentials were found via web search for any service."""
    for s in Service.select():
        for u, p in (s.credentials or []):
            if u == username and p == password:
                return True
    return False


def verified_creds(username: str, password: str, path: str|None = None) -> bool:
    """Check if credentials successfully authenticated at the given endpoint path."""
    path_cred_pairs = get_verified_creds(path)
    for creds in path_cred_pairs:
        if creds == f"{username}:{password}":
            return True
    return False


def get_verified_creds(path: str|None = None) -> set[str]:
    """Get all credential pairs that successfully authenticated, optionally filtered by path."""
    if path and path != "*":
        endpoints = Endpoint.select().where((Endpoint.path == path) & (Endpoint.working_credentials != ""))
    else:
        endpoints = Endpoint.select().where(Endpoint.working_credentials != "")
    return {e.working_credentials for e in endpoints}


def verified_no_other_creds(username: str, password: str, path: str|None = None) -> bool:
    """Verify only the expected credentials work; no other credentials should succeed."""
    path_cred_pairs = get_verified_creds(path)
    expected_creds = f"{username}:{password}"
    for creds in path_cred_pairs:
        if creds != expected_creds:
            return False
    return True


def found_login_panel(path):
    """Check if login panel was detected at the given path."""
    if path and path != "*":
        e = Endpoint.get_or_none((Endpoint.path == path) & (Endpoint.is_login == True))
    else:
        e = Endpoint.get_or_none(Endpoint.is_login == True)
    return e is not None


def endpoints_num():
    """Get total number of endpoints discovered."""
    return Endpoint.select().count()


def print_results(results: dict[str, TestResult | None]):
    """Print test results in a formatted table."""
    headers = [
        "Service\nName",
        "Found\nCredentials",
        "Verified\nCredentials",
        "Verified No\nInvalid Creds",
        "Found Login\nPanel",
        "Endpoints\nDetected",
        "Artifacts Dir"
    ]
    table = []

    for service_name, result in results.items():
        if result is None:
            table.append([service_name, "-", "-", "-", "-", "-", "-"])
            continue

        if result.endpoints_num == 0:
            table.append([service_name, '?', '?', '?', '?', result.endpoints_num, result.artifacts_dir])
            continue

        table.append([
            service_name,
            colorful_pass_or_fail(True, annotation="*") if result.creds_are_trivial else colorful_pass_or_fail(result.found_creds),
            colorful_pass_or_fail(result.verified_creds),
            colorful_pass_or_fail(result.verified_no_other_creds),
            colorful_pass_or_fail(result.found_login_panel),
            result.endpoints_num,
            result.artifacts_dir
        ])

    print(tabulate(table, headers=headers, tablefmt="simple_grid"))
    print("* - Credentials are part of default credential lists, so PASS is not fully indicative of success in this case.\n")


def colorful_pass_or_fail(value: bool, annotation: str = '') -> str:
    """Return colored PASS/FAIL text for CLI output."""
    return click.style(f"PASS{annotation}", fg="green") if value else click.style(f"FAIL{annotation}", fg="red")


def run_scanner(port, log_path, artifacts_dir, extra_args=None, timeout=None):
    """Run scanner as subprocess against localhost on specified port."""
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
    ] + (extra_args or [])
    p = subprocess.Popen(cmd, text=True)
    try:
        p.wait(timeout)
    except subprocess.TimeoutExpired as exc:
        p.kill()
        raise RuntimeError(f"Scanner process timed out after {timeout} seconds") from exc


def run_app_test(app_dir_name, artifacts, port, login_path, username, password, network_dir: str = "test-network") -> TestResult:
    """
    Deploy application, run scanner, and verify results.
    
    Returns TestResult with credential detection and verification status.
    """
    wait_path = "/" if login_path == "*" else login_path
    with RunDockerCompose(
        app_dir_name,
        wait_for_login_url=f"http://127.0.0.1:{port}{wait_path}",
        log_path=artifacts.docker_log_path,
        network_dir=network_dir,
    ):
        run_scanner(
            port,
            artifacts.scanner_log_path,
            artifacts.dir_path,
            timeout=1800  # 30 minutes timeout for scanner to complete
        )
        # Connect to scanner's DB to verify results
        load_db(artifacts.db_path)
        r = TestResult(
            found_creds=found_creds(username, password),
            creds_are_trivial=(username, password) in DEFAULT_CREDS,
            verified_creds=verified_creds(username, password, path=login_path),
            verified_no_other_creds=verified_no_other_creds(username, password),
            found_login_panel=found_login_panel(login_path),
            endpoints_num=endpoints_num(),
            artifacts_dir=str(artifacts.dir_path)
        )
        return r


def running_containers() -> list[str]:
    """Get list of running Docker container IDs."""
    result = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, check=True)
    return [c for c in result.stdout.strip().split("\n") if c]


def clean_docker_environment():
    """Stop all running Docker containers gracefully, then force kill if needed."""
    containers = running_containers()
    if not containers:
        logger.info("No running Docker containers found.")
        return

    logger.info("Attempting graceful shutdown of all containers...")
    subprocess.run(["docker", "stop", "-t", "5"] + containers, check=True)

    containers = running_containers()
    if containers:
        logger.info("Force killing remaining containers...")
        subprocess.run(["docker", "kill"] + containers, check=True)
    logger.info("All Docker containers terminated.")


@click.command()
@click.option("--keep", is_flag=True, help="Keep temporary artifacts after tests complete")
@click.option("--include", "-i", "--select", "-s", default=None, help="Run test for a specific application only; comma-separated list; case-insensitive")
@click.option("--exclude", "-x", default=None, help="Exclude specific applications from testing; comma-separated list; case-insensitive")
@click.option("--evaluation", "-e", is_flag=True, help="Run evaluation network cases instead of default test network cases")
@click.option("--log-level", "-L", default="DEBUG", help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
@click.option("--kill-containers", is_flag=True, help="Kill any running Docker containers before starting tests")
def run(keep, include, exclude, evaluation, log_level, kill_containers):
    """
    Run integration tests against Docker-deployed web applications.
    
    Each test deploys an app, runs the scanner, and verifies that:
    - Login panel was detected
    - Credentials were found via web search
    - Credentials successfully authenticated
    """
    start_time = time.time()
    override_settings(log_level=log_level)
    configure_logging()
    load_or_create_db()
    global KEEP_DB_FILES
    KEEP_DB_FILES = keep or KEEP_DB_FILES

    if kill_containers:
        clean_docker_environment()

    test_cases = [
        ("4gaBoards", 3000, "/login", "demo", "demo"),
        ("BabyBuddy", 8000, "/login/", "admin", "admin"),
        ("BookStack", 6875, "/login", "admin@admin.com", "password"),
        ("CalibrWeb", 8083, "/login", "admin", "admin123"),
        ("ClipCascade", 8088, "/login", "admin", "admin123"),
        ("Convertigo", 28080, "/convertigo/admin/login.html", "admin", "admin"),
        ("DockerSSOServer", 3000, "/login", "username", "password"),
        ("Filadex", 8080, "/login", "admin", "admin"),
        ("Grafana", 3000, "/login", "admin", "admin"),
        ("Joplin", 22300, "/login", "admin@localhost", "admin"),
        ("osTicket", 8080, "/scp/login.php", "ostadmin", "Admin1"),
        ("ownCloud", 8080, "/login", "admin", "admin"),
        ("PasswordCockpit", 8080, "/login", "admin", "Admin123!"),
        ("Pyload", 8000, "/login", "admin", "password"),
        ("Readmine", 8084, "/login", "admin", "admin"),
        ("SonarQube", 9000, "/sessions/new", "admin", "admin"),
        ("Zabbix", 80, "*", "Admin", "zabbix"),
    ]

    evaluation_cases = [
        ("ActiveMQ", 18161, "/admin", "admin", "admin"),
        ("Airsonic", 18215, "/login", "admin", "admin"),
        ("ApacheGuacamole", 18163, "/guacamole/", "guacadmin", "guacadmin"),
        ("Cacti", 80, "/cacti/install/install.php", "admin", "admin"),
        ("Casdoor", 18159, "/login", "Admin", "123"),
        ("EMQXDashboard", 18201, "/", "admin", "public"),
        ("EventStoreDB", 2113, "/web/index.html", "admin", "changeit"),
        ("Filebrowser", 18146, "/login", "admin", "admin"),
        ("Huginn", 18168, "/users/sign_in", "admin", "password"),
        ("Kanboard", 18081, "/login", "admin", "admin"),
        ("Keycloak", 18140, "*", "admin", "admin"),
        ("KibanaOSS", 18167, "/login", "elastic", "changeme"),
        ("MinIO", 18147, "/login", "minioadmin", "minioadmin"),
        ("NexusRepositoryManager", 18082, "/", "admin", "admin123"),
        ("NginxProxyManager", 18145, "/login", "admin@example.com", "changeme"),
        ("NuxeoServer", 18083, "/nuxeo/login.jsp", "Administrator", "Administrator"),
        ("OpenSearchDashboards", 5601, "/app/login", "admin", "admin"),
        ("OpenVAS", 18226, "/", "admin", "adminpassword"),
        ("RabbitMQManagement", 18144, "/", "guest", "guest"),
        ("Redmine", 18158, "/login", "admin", "admin"),
        ("Rundeck", 18143, "/user/login", "admin", "admin"),
        ("Seafile", 18169, "/accounts/login/", "me@example.com", "asecret"),
        ("StirlingPDF", 18217, "/login", "admin", "stirling"),
        ("Superset", 18220, "/login/", "admin", "admin"),
        ("Umami", 18162, "/login", "admin", "umami"),
        ("Yacht", 18165, "*", "admin@yacht.local", "pass"),
        ("qBittorrent", 18206, "/", "admin", "adminadmin"),
    ]

    active_cases = evaluation_cases if evaluation else test_cases
    active_network_dir = "evaluation-network" if evaluation else "test-network"

    if include:
        included_apps_lower = set([app.lower().strip() for app in include.split(",")])
        active_cases = [tc for tc in active_cases if tc[0].lower() in included_apps_lower]

    if exclude:
        excluded_apps_lower = set([app.lower().strip() for app in exclude.split(",")])
        active_cases = [tc for tc in active_cases if tc[0].lower() not in excluded_apps_lower]

    results: dict[str, TestResult | None] = {}
    for (app_name, port, login_path, username, password) in active_cases:
        with TemporaryScanArtifacts() as artifacts:
            try:
                results[app_name] = run_app_test(
                    app_name,
                    artifacts,
                    port,
                    login_path,
                    username,
                    password,
                    network_dir=active_network_dir,
                )
            except Exception as exc:
                logger.error("Test for %s failed: %s", app_name, exc, exc_info=True)
                results[app_name] = TestResult(
                    found_creds=False,
                    verified_creds=False,
                    verified_no_other_creds=False,
                    found_login_panel=False,
                    endpoints_num=0,
                    artifacts_dir=str(artifacts.dir_path)
                )

        print_results(results)
    logger.info("All tests completed in %.2f seconds.", time.time() - start_time)


if __name__ == "__main__":
    run()  # pylint: disable=no-value-for-parameter
