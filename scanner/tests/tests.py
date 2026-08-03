# Integration test suite for the scanner against real web applications.

import json
import re
import subprocess
import random
import logging
import time
from pathlib import Path
from dataclasses import dataclass
from tabulate import tabulate
import click
import yaml
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
    duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_estimated: bool = False
    app_version: str = "?"


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


def _normalize_name(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())


def _split_image(image: str) -> tuple[str, str]:
    """Split a docker image reference into (repo, tag); defaults tag to 'latest'."""
    if ":" in image:
        repo, tag = image.rsplit(":", 1)
        if "/" in tag:  # the colon was part of a registry:port, not a tag
            return image, "latest"
        return repo, tag
    return image, "latest"


def find_compose_file(app_dir_name: str, network_dir: str) -> Path | None:
    """Locate the docker-compose file for an app, or None if not found."""
    base = Path(__file__).resolve().parent / network_dir / app_dir_name
    for fname in ("docker-compose.yaml", "docker-compose.yml"):
        candidate = base / fname
        if candidate.exists():
            return candidate
    return None


def get_app_version(app_dir_name: str, network_dir: str) -> str:
    """
    Determine the app's version/image by reading its docker-compose file.

    Picks the service whose name or image best matches the app directory name
    (to skip sidecar services like databases). An exact normalized match always
    wins first (so e.g. an "owncloud-db" sidecar can't shadow the "owncloud"
    service just because its name also contains "owncloud"); otherwise falls
    back to the first substring match, then the first service with an image.
    """
    compose_file = find_compose_file(app_dir_name, network_dir)
    if compose_file is None:
        return "?"

    try:
        with compose_file.open("r", encoding="utf-8") as fin:
            compose = yaml.safe_load(fin)
    except Exception as e:
        logger.warning("Failed to parse docker-compose file for %s: %s", app_dir_name, e)
        return "?"

    services = (compose or {}).get("services") or {}
    target = _normalize_name(app_dir_name)

    first_image = None
    substring_match = None
    for service_name, service_def in services.items():
        image = (service_def or {}).get("image")
        if not image:
            continue
        if first_image is None:
            first_image = image

        repo, _ = _split_image(image)
        norm_service = _normalize_name(service_name)
        norm_repo = _normalize_name(repo)

        if norm_service == target or norm_repo == target:
            return image

        if substring_match is None and (target in norm_service or norm_service in target or target in norm_repo or norm_repo in target):
            substring_match = image

    return substring_match or first_image or "?"


def read_token_usage(artifacts_dir: Path) -> tuple[int, int, bool]:
    """Read (input_tokens, output_tokens, estimated) written by the scanner subprocess, or (0, 0, False) if unavailable."""
    token_usage_path = artifacts_dir / "token_usage.json"
    try:
        data = json.loads(token_usage_path.read_text())
        return int(data.get("input_tokens", 0)), int(data.get("output_tokens", 0)), bool(data.get("estimated", False))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return 0, 0, False


def print_results(results: dict[str, TestResult | None]):
    """Print test results in a formatted table, followed by a running total for the whole suite."""
    headers = [
        "Service\nName",
        "App\nVersion",
        "Found\nCredentials",
        "Verified\nCredentials",
        "Verified No\nInvalid Creds",
        "Found Login\nPanel",
        "Endpoints\nDetected",
        "Time\n(s)",
        "Input\nTokens",
        "Output\nTokens",
        "Artifacts Dir"
    ]
    table = []

    for service_name, result in results.items():
        if result is None:
            table.append([service_name, "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"])
            continue

        input_tokens_cell = _fmt_tokens(result.input_tokens, result.tokens_estimated)
        output_tokens_cell = _fmt_tokens(result.output_tokens, result.tokens_estimated)

        if result.endpoints_num == 0:
            table.append([
                service_name, result.app_version, '?', '?', '?', '?', result.endpoints_num,
                f"{result.duration_seconds:.1f}", input_tokens_cell, output_tokens_cell, result.artifacts_dir
            ])
            continue

        table.append([
            service_name,
            result.app_version,
            colorful_pass_or_fail(True, annotation="*") if result.creds_are_trivial else colorful_pass_or_fail(result.found_creds),
            colorful_pass_or_fail(result.verified_creds),
            colorful_pass_or_fail(result.verified_no_other_creds),
            colorful_pass_or_fail(result.found_login_panel),
            result.endpoints_num,
            f"{result.duration_seconds:.1f}",
            input_tokens_cell,
            output_tokens_cell,
            result.artifacts_dir
        ])

    print(tabulate(table, headers=headers, tablefmt="simple_grid"))
    print("* - Credentials are part of default credential lists, so PASS is not fully indicative of success in this case.")

    completed = [r for r in results.values() if r is not None]
    total_duration = sum(r.duration_seconds for r in completed)
    total_input_tokens = sum(r.input_tokens for r in completed)
    total_output_tokens = sum(r.output_tokens for r in completed)
    any_estimated = any(r.tokens_estimated for r in completed)
    totals_marker = "~" if any_estimated else ""
    print(
        f"Run totals so far ({len(completed)} apps): "
        f"time={total_duration:.1f}s, input_tokens={total_input_tokens}{totals_marker}, output_tokens={total_output_tokens}{totals_marker}"
    )
    if any_estimated:
        print("~ - Token counts estimated with a local tokenizer because the LLM API did not return usage metadata (approximate).")
    print("Note: token counts include cached LLM responses, since those still represent tokens the pipeline logically processed, not just newly-billed API calls.\n")


def _fmt_tokens(value: int, estimated: bool) -> str:
    return f"{value}~" if estimated else str(value)


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
        input_tokens, output_tokens, tokens_estimated = read_token_usage(artifacts.dir_path)
        r = TestResult(
            found_creds=found_creds(username, password),
            creds_are_trivial=(username, password) in DEFAULT_CREDS,
            verified_creds=verified_creds(username, password, path=login_path),
            verified_no_other_creds=verified_no_other_creds(username, password),
            found_login_panel=found_login_panel(login_path),
            endpoints_num=endpoints_num(),
            artifacts_dir=str(artifacts.dir_path),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_estimated=tokens_estimated,
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
            app_start = time.time()
            app_version = get_app_version(app_name, active_network_dir)
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
            results[app_name].duration_seconds = time.time() - app_start
            results[app_name].app_version = app_version

        print_results(results)

    total_duration = time.time() - start_time
    completed_results = [r for r in results.values() if r is not None]
    total_input_tokens = sum(r.input_tokens for r in completed_results)
    total_output_tokens = sum(r.output_tokens for r in completed_results)
    any_estimated = any(r.tokens_estimated for r in completed_results)
    totals_marker = "~" if any_estimated else ""
    print(f"Entire run: time={total_duration:.1f}s, input_tokens={total_input_tokens}{totals_marker}, output_tokens={total_output_tokens}{totals_marker}")
    if any_estimated:
        print("~ - Token counts estimated with a local tokenizer because the LLM API did not return usage metadata (approximate).")
    print("Note: token counts include cached LLM responses, since those still represent tokens the pipeline logically processed, not just newly-billed API calls.")
    logger.info(
        "All tests completed in %.2f seconds. Total tokens: input=%d, output=%d (estimated=%s).",
        total_duration, total_input_tokens, total_output_tokens, any_estimated
    )


if __name__ == "__main__":
    run()  # pylint: disable=no-value-for-parameter
