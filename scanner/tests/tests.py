import subprocess
import random
from pathlib import Path
from dataclasses import dataclass
from tabulate import tabulate
import click
from .startup_script import RunDockerCompose
from scanner.db import Endpoint, Service, init_db
from scanner.settings import Settings

KEEP_DB_FILES = False

@dataclass
class TestResult:
    service_name: str
    found_creds: bool
    verified_creds: bool
    found_login_panel: bool
    db_path: str = ""


class TemporaryDatabase:
    def __init__(self):
        scan_id = random.randint(100000, 999999)
        self.path = Path(f"/tmp/scanner-test-{scan_id}.db")

    def __enter__(self):
        return self.path

    def __exit__(self, exc_type, exc_value, traceback):
        if not KEEP_DB_FILES:
            self.path.unlink(missing_ok=True)


def found_creds(username, password):
    for s in Service.select():
        print(f"Checking service {s}")
        # s.credentials may be stored as list of lists (JSON) or tuples; compare values robustly
        for u, p in (s.credentials or []):
            if u == username and p == password:
                return True
    return False

def verified_creds(path, username, password):
    e = Endpoint.get_or_none((Endpoint.path == path) & (Endpoint.working_credentials == f"{username}:{password}"))
    return e is not None

def found_login_panel(path):
    e = Endpoint.get_or_none((Endpoint.path == path) & (Endpoint.is_login == True))
    return e is not None

def check_result(service_name, login_path, username, password):
    return TestResult(
        service_name=service_name,
        found_creds=found_creds(username, password),
        verified_creds=verified_creds(login_path, username, password),
        found_login_panel=found_login_panel(login_path)
    )

def print_results(results: list[TestResult]):
    headers = ["Service Name", "Found Credentials", "Verified Credentials", "Found Login Panel", "DB Path"]
    table = [
        [
            result.service_name,
            emojify(result.found_creds),
            emojify(result.verified_creds),
            emojify(result.found_login_panel),
            result.db_path
        ] for result in results
    ]
    print(tabulate(table, headers=headers, tablefmt="grid"))

def emojify(value: bool):
    return "✅" if value else "❌"

def run_scanner(port, extra_args=[]):
    cmd = ["python", "-m", "scanner.main", "127.0.0.1", "-p", str(port), "-L", "DEBUG"] + extra_args
    p = subprocess.Popen(cmd, text=True)
    p.wait()


def run_app_test(app_dir_name, port, login_path, username, password) -> TestResult:
    with TemporaryDatabase() as temp_db_path:
        with RunDockerCompose(f"{app_dir_name}/docker-compose.yaml", wait_for_port=port):
            run_scanner(port, extra_args=["--db-path", str(temp_db_path)])
            # Rebind our ORM to the same temporary DB used by the scanner run
            Settings().configure_cli_arguments(db_path=str(temp_db_path))
            init_db()
            r = check_result(app_dir_name, login_path, username, password)
            r.db_path = str(temp_db_path)
            return r

@click.command()
@click.option("--keep", is_flag=True, help="Keep temporary database files after tests complete")
def run(keep):
    init_db()
    global KEEP_DB_FILES
    KEEP_DB_FILES = keep

    #print_results([
    #    run_app_test("4gaBoards", 3000, "/admin", "demo", "demo")
    #])

    test_cases = [
        ("4gaBoards", 3000, "/login", "demo", "demo"),
        ("BabyBuddy", 8000, "/login/", "admin", "admin"),
        ("BookStack", 6875, "/login", "admin@admin.com", "password"),
        ("CalibrWeb", 8083, "/login", "admin", "admin123"),
        ("ClipCascade", 8088, "/login", "admin", "admin123"),
        ("Convertigo", 28080, "/convertigo/index.html", "admin", "admin"),
        ("DataLens", 8080, "/auth/signin", "admin", "admin"),
        ("DockerSSOServer", 3000, "/login", "username", "password"),
        ("Filadex", 8080, "/login", "admin", "admin"),
        ("Grafana", 3000, "/login", "admin", "admin"),
        ("Joplin", 22300, "/login", "admin@localhost", "admin"),
        # ("MongoExpress", 8081, "/", "admin", "pass"), WARNING: MongoDB 5.0+ requires a CPU with AVX support, and your current system does not appear to have that!
        ("osTicket", 8080, "/scp/login.php", "ostadmin", "Admin1"),
        ("ownCloud", 8080, "/login", "admin", "admin"),
        ("PasswordCockpit", 8080, "/login", "admin", "Admin123!"),
        ("Pyload", 8000, "/login", "admin", "password"),
        ("Rainloop", 80, "/", "admin", "12345"),
        ("Readmine", 8084, "/login", "admin", "admin"),
        ("SonarQube", 9000, "/sessions/new", "admin", "admin"),
        ("Zabbix", 80, "/", "Admin", "zabbix")
    ]

    results: list[TestResult] = []
    for (app_name, port, login_path, username, password) in test_cases:
        try:
            results.append(run_app_test(app_name, port, login_path, username, password))
        except Exception as exc:
            print(f"Test for {app_name} failed: {exc}")
            results.append(
                TestResult(
                    service_name=app_name,
                    found_creds=False,
                    verified_creds=False,
                    found_login_panel=False,
                    db_path="ERROR"
                )
            )

    print_results(results)

if __name__ == "__main__":
    run()  # pylint: disable=no-value-for-parameter
