"""External evaluation runner using Changeme (Docker).

Goal: provide a scanner-independent evaluation harness.

Workflow per app:
1) docker compose up the app from scanner/tests/*-network/<App>/docker-compose.y*ml
2) wait until the login URL is up (simple HTTP poll; checks for login markers)
3) run changeme in Docker (with a Redis sidecar) and write results.csv
4) parse results.csv and print a concise PASS/FAIL summary
5) docker compose down
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger("evaluate_external")


# Kept in sync with scanner/db/models.py; used only for result annotation.
DEFAULT_CREDS = [("admin", "admin"), ("admin", "password"), ("username", "password")]


@dataclass
class EvalResult:
    found_creds: bool
    found_expected_creds: bool
    found_only_expected_creds: bool
    findings_count: int
    artifacts_dir: str
    creds_are_trivial: bool


class TemporaryEvalArtifacts:
    def __init__(self, keep: bool):
        scan_id = random.randint(100000, 999999)
        self.keep = keep
        self.dir_path = Path("/tmp/evaluate_artifacts") / f"changeme-eval-{scan_id}"
        self.docker_log_path = self.dir_path / "docker.log"
        self.changeme_log_path = self.dir_path / "changeme.log"
        self.results_csv_path = self.dir_path / "results.csv"

    def __enter__(self):
        self.dir_path.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if not self.keep:
            self.results_csv_path.unlink(missing_ok=True)
            self.changeme_log_path.unlink(missing_ok=True)
            self.docker_log_path.unlink(missing_ok=True)
        return False


def _parse_csv_list(value: str | None) -> set[str]:
    if not value:
        return set()
    return {v.strip().lower() for v in value.split(",") if v.strip()}


def _append_log(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fout:
        fout.write(text)
        if not text.endswith("\n"):
            fout.write("\n")


def _run_checked(cmd: list[str], *, cwd: Path | None = None, log_path: Path | None = None, timeout: int | None = None) -> None:
    logger.debug("Running: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        if log_path:
            _append_log(log_path, f"[TIMEOUT] {cmd}\n{exc}")
        raise

    if log_path:
        _append_log(log_path, f"$ {' '.join(cmd)}")
        if proc.stdout:
            _append_log(log_path, proc.stdout)
        if proc.stderr:
            _append_log(log_path, proc.stderr)

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)


def running_containers() -> list[str]:
    proc = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, check=True)
    return [c for c in proc.stdout.strip().split("\n") if c]


def clean_docker_environment() -> None:
    containers = running_containers()
    if not containers:
        logger.info("No running Docker containers found.")
        return
    logger.info("Stopping %d running Docker containers...", len(containers))
    subprocess.run(["docker", "stop", "-t", "5"] + containers, check=False)
    containers = running_containers()
    if containers:
        subprocess.run(["docker", "kill"] + containers, check=False)


def find_compose_file(app_dir_name: str, network_dir: str) -> Path:
    base = Path(__file__).resolve().parent.parent / "scanner" / "tests" / network_dir / app_dir_name
    if not base.exists():
        raise FileNotFoundError(f"App directory not found: {base}")
    for fname in ("docker-compose.yaml", "docker-compose.yml"):
        candidate = base / fname
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No docker-compose.yaml/yml found in {base}")


def docker_compose_up(compose_file: Path, log_path: Path) -> None:
    _run_checked(["docker", "compose", "-f", str(compose_file), "up", "-d"], cwd=compose_file.parent, log_path=log_path)


def docker_compose_down(compose_file: Path, log_path: Path) -> None:
    # -v removes volumes, --remove-orphans avoids leftovers between runs
    try:
        _run_checked(
            ["docker", "compose", "-f", str(compose_file), "down", "-v", "--remove-orphans"],
            cwd=compose_file.parent,
            log_path=log_path,
            timeout=30,
        )
    except Exception:
        # Best-effort kill to avoid leaving containers around.
        subprocess.run(["docker", "compose", "-f", str(compose_file), "kill"], cwd=str(compose_file.parent), check=False)


def wait_login_panel_up(url: str, *, timeout_s: int = 120) -> None:
    """Poll URL until it looks "ready" (HTTP responds and resembles a login page).

    We intentionally avoid full browser rendering (selenium) so this check is
    heuristic-based and must handle SPA login pages where the password input is
    created client-side.
    """
    deadline = time.time() + timeout_s
    wait = 1.0
    last_error: str | None = None

    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "evaluate_external"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read(2_000_000)  # cap to 2MB
            text = body.decode("utf-8", errors="ignore")
            looks_like_login = (
                "type=\"password\"" in text
                or "type='password'" in text
                or "type=password" in text
                or "password" in text.lower()
                or "login" in text.lower()
                or "sign in" in text.lower()
            )

            if 200 <= int(status) < 400 and (len(text) > 0) and looks_like_login:
                time.sleep(3)
                return

            last_error = f"not ready yet (status={status}, login_markers={looks_like_login})"
        except urllib.error.URLError as exc:
            last_error = f"url error: {exc}"
        except Exception as exc:
            last_error = f"error: {exc}"

        time.sleep(wait)
        wait = min(wait * 2.0, 10.0)

    raise TimeoutError(f"Timeout waiting for login panel at {url} ({last_error})")


def _docker_rm_f(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def _docker_get_published_host_port(container_name: str, container_port: int) -> int:
    """Return the published host port for a container port."""
    proc = subprocess.run(
        ["docker", "port", container_name, f"{container_port}/tcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to get docker port mapping for {container_name}: {proc.stderr.strip()}")

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        host_port_str = line.rsplit(":", 1)[-1]
        try:
            return int(host_port_str)
        except ValueError:
            continue

    raise RuntimeError(f"Could not parse docker port mapping for {container_name}: {proc.stdout!r}")


def run_changeme_in_docker(
    *,
    target: str,
    output_csv_path: Path,
    changeme_log_path: Path,
    protocols: str,
    threads: int,
    timeout_s: int,
    delay_ms: int,
    image: str,
) -> None:
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    if output_csv_path.exists():
        output_csv_path.unlink()

    redis_name = f"changeme-redis-{random.randint(100000, 999999)}"
    try:
        # Bind Redis to a random localhost port to avoid conflicts, and so the
        # Changeme container can reach it via --network host.
        _run_checked(
            ["docker", "run", "-d", "--name", redis_name, "-p", "127.0.0.1::6379", "redis"],
            log_path=changeme_log_path,
        )
        redis_port = _docker_get_published_host_port(redis_name, 6379)

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--network",
            "host",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            # Fedora/RHEL systems with SELinux typically require :Z/:z for
            # containers to write into host-mounted directories.
            f"{str(output_csv_path.parent)}:/mnt:Z",
            image,
            "./changeme.py",
            "--noversion",
            "--redishost",
            "127.0.0.1",
            "--redisport",
            str(redis_port),
            "--output",
            f"/mnt/{output_csv_path.name}",
            "--protocols",
            protocols,
            "--threads",
            str(threads),
            "--timeout",
            str(timeout_s),
            "--delay",
            str(delay_ms),
            target,
        ]
        _run_checked(docker_cmd, log_path=changeme_log_path)
    finally:
        _docker_rm_f(redis_name)


def parse_changeme_results(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append(
                {
                    "name": (row.get("name") or "").strip(),
                    "username": (row.get("username") or "").strip(),
                    "password": (row.get("password") or "").strip(),
                    "target": (row.get("target") or "").strip(),
                }
            )
        return rows


def evaluate_case(
    *,
    app_dir_name: str,
    artifacts: TemporaryEvalArtifacts,
    port: int,
    login_path: str,
    expected_username: str,
    expected_password: str,
    network_dir: str,
    protocols: str,
    threads: int,
    timeout_s: int,
    delay_ms: int,
    changeme_image: str,
    target_mode: str,
) -> EvalResult:
    compose_file = find_compose_file(app_dir_name, network_dir)
    docker_compose_up(compose_file, artifacts.docker_log_path)
    try:
        wait_path = "/" if login_path == "*" else login_path
        wait_url = f"http://127.0.0.1:{port}{wait_path}"
        wait_login_panel_up(wait_url, timeout_s=180)

        # Changeme runs in Docker with --network host, so it can scan localhost
        # targets directly.
        if target_mode == "proto":
            target = f"http://127.0.0.1:{port}"
        elif target_mode == "host":
            target = "127.0.0.1"
        elif target_mode == "subnet":
            target = "127.0.0.1/32"
        else:
            raise ValueError(f"Unknown target_mode: {target_mode}")

        run_changeme_in_docker(
            target=target,
            output_csv_path=artifacts.results_csv_path,
            changeme_log_path=artifacts.changeme_log_path,
            protocols=protocols,
            threads=threads,
            timeout_s=timeout_s,
            delay_ms=delay_ms,
            image=changeme_image,
        )

        rows = parse_changeme_results(artifacts.results_csv_path)
        expected_pair = (expected_username, expected_password)
        found_any = len(rows) > 0
        found_expected = any((r.get("username"), r.get("password")) == expected_pair for r in rows)
        unique_pairs = {(r.get("username"), r.get("password")) for r in rows}
        found_only_expected = (not found_any) or (unique_pairs == {expected_pair})

        return EvalResult(
            found_creds=found_any,
            found_expected_creds=found_expected,
            found_only_expected_creds=found_only_expected,
            findings_count=len(rows),
            artifacts_dir=str(artifacts.dir_path),
            creds_are_trivial=expected_pair in DEFAULT_CREDS,
        )
    finally:
        docker_compose_down(compose_file, artifacts.docker_log_path)


def _fmt_bool(value: bool, *, star: bool = False) -> str:
    if value:
        return "PASS*" if star else "PASS"
    return "FAIL"


def print_results(results: dict[str, EvalResult], *, title: str | None = None) -> None:
    if title:
        print(f"\n=== {title} ===")

    headers = ["Service", "Any", "Expected", "OnlyExpected", "Findings", "Artifacts"]
    rows: list[list[str]] = [headers]
    for name, r in results.items():
        rows.append(
            [
                name,
                _fmt_bool(r.found_creds),
                _fmt_bool(r.found_expected_creds, star=r.creds_are_trivial),
                _fmt_bool(r.found_only_expected_creds),
                str(r.findings_count),
                r.artifacts_dir,
            ]
        )

    widths = [max(len(row[i]) for row in rows) for i in range(len(headers))]
    sep = " | "
    line = "-+-".join("-" * w for w in widths)

    for idx, row in enumerate(rows):
        print(sep.join(col.ljust(widths[i]) for i, col in enumerate(row)))
        if idx == 0:
            print(line)
    print("\n* Expected creds are trivial/default (extra ambiguity).")


def _run_suite(
    *,
    suite_title: str,
    network_dir: str,
    cases: list[tuple[str, int, str, str, str]],
    include_set: set[str],
    exclude_set: set[str],
    keep: bool,
    protocols: str,
    threads: int,
    timeout_s: int,
    delay_ms: int,
    changeme_image: str,
    target_mode: str,
) -> dict[str, EvalResult]:
    active_cases = cases
    if include_set:
        active_cases = [tc for tc in active_cases if tc[0].lower() in include_set]
    if exclude_set:
        active_cases = [tc for tc in active_cases if tc[0].lower() not in exclude_set]

    results: dict[str, EvalResult] = {}
    for (app_name, port, login_path, username, password) in active_cases:
        logger.info("Evaluating %s (%s)...", app_name, suite_title)
        with TemporaryEvalArtifacts(keep=keep) as artifacts:
            try:
                results[app_name] = evaluate_case(
                    app_dir_name=app_name,
                    artifacts=artifacts,
                    port=port,
                    login_path=login_path,
                    expected_username=username,
                    expected_password=password,
                    network_dir=network_dir,
                    protocols=protocols,
                    threads=threads,
                    timeout_s=timeout_s,
                    delay_ms=delay_ms,
                    changeme_image=changeme_image,
                    target_mode=target_mode,
                )
            except Exception as exc:
                logger.error("Evaluation for %s failed: %s", app_name, exc, exc_info=True)
                results[app_name] = EvalResult(
                    found_creds=False,
                    found_expected_creds=False,
                    found_only_expected_creds=False,
                    findings_count=0,
                    artifacts_dir=str(artifacts.dir_path),
                    creds_are_trivial=False,
                )

    print_results(results, title=suite_title)
    return results


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Evaluate apps with changeme (Docker)")
    ap.add_argument("--keep", action="store_true", help="Keep artifacts in /tmp/evaluate_artifacts")
    ap.add_argument("-s", "--select", "--include", dest="include", default=None, help="Comma-separated app names to include")
    ap.add_argument("-x", "--exclude", dest="exclude", default=None, help="Comma-separated app names to exclude")
    ap.add_argument("-e", "--evaluation", action="store_true", help="Use evaluation-network instead of test-network")
    ap.add_argument("--both", action="store_true", help="Run both test-network and evaluation-network")
    ap.add_argument("--kill-containers", action="store_true", help="Kill any running Docker containers before starting")
    ap.add_argument("--changeme-image", default="ztgrace/changeme:latest", help="Changeme Docker image")
    ap.add_argument("--protocols", default="http", help="Changeme protocols (comma-separated)")
    ap.add_argument("--threads", type=int, default=10, help="Changeme threads")
    ap.add_argument("--timeout", dest="timeout_s", type=int, default=10, help="Changeme request timeout (seconds)")
    ap.add_argument("--delay", dest="delay_ms", type=int, default=500, help="Changeme delay (ms)")
    ap.add_argument("--target-mode", choices=["proto", "host", "subnet"], default="proto", help="Changeme target style")
    ap.add_argument("-L", "--log-level", default="INFO", help="Log level (DEBUG/INFO/WARNING/ERROR)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="[%(asctime)s][%(levelname)s] %(message)s")

    if args.kill_containers:
        clean_docker_environment()

    test_cases: list[tuple[str, int, str, str, str]] = [
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

    evaluation_cases: list[tuple[str, int, str, str, str]] = [
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
        ("Keycloak", 18140, "/realms/master/protocol/openid-connect/auth", "admin", "admin"),
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

    include_set = _parse_csv_list(args.include)
    exclude_set = _parse_csv_list(args.exclude)

    suites: list[tuple[str, str, list[tuple[str, int, str, str, str]]]] = []
    if args.both:
        suites = [
            ("test-network", "test-network", test_cases),
            ("evaluation-network", "evaluation-network", evaluation_cases),
        ]
    else:
        if args.evaluation:
            suites = [("evaluation-network", "evaluation-network", evaluation_cases)]
        else:
            suites = [("test-network", "test-network", test_cases)]

    start_time = time.time()
    for (suite_title, network_dir, cases) in suites:
        _run_suite(
            suite_title=suite_title,
            network_dir=network_dir,
            cases=cases,
            include_set=include_set,
            exclude_set=exclude_set,
            keep=args.keep,
            protocols=args.protocols,
            threads=args.threads,
            timeout_s=args.timeout_s,
            delay_ms=args.delay_ms,
            changeme_image=args.changeme_image,
            target_mode=args.target_mode,
        )

    logger.info("All evaluations completed in %.2f seconds.", time.time() - start_time)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
