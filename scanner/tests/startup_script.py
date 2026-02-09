import subprocess
import logging
import threading
from pathlib import Path
from seleniumbase import sb_cdp

logger = logging.getLogger('scanner.tests.startup_script')

class StartupScript:
    """
    Helper class for tests to automatically deploy an app using a startup script from apps/
    Implements the context manager protocol to start and stop the script.
    """

    def __init__(self, cmd: list[str], wait_for_login_url: int, timeout: int = 30, cwd="/tmp", log_path: Path | None = None):
        self.cmd = cmd
        self.cwd = cwd
        self.wait_for_login_url = wait_for_login_url
        self.process = None
        self.timeout = timeout
        self.log_path = log_path
        self.log_file = None

    def __enter__(self):
        def stream_logs(process, log_file):
            for line in process.stdout:
                if log_file:
                    log_file.write(line)
                    log_file.flush()
                else:
                    print(line, end='')

        subprocess.run(["docker", "container", "prune", "-f"], check=True)
        subprocess.run(["docker", "network", "prune", "-f"], check=True)

        self.process = subprocess.Popen(
            self.cmd,
            cwd=self.cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
        )

        if self.log_path:
            self.log_file = self.log_path.open("w", encoding="utf-8")

        threading.Thread(target=stream_logs, args=(self.process, self.log_file), daemon=True).start()

        if not self.wait_login_panel_up(self.wait_for_login_url, timeout=self.timeout):
            raise TimeoutError(f"Timeout reached while waiting for login panel {self.wait_for_login_url} to come up.")

        logger.info("Startup command %s ran successfully.", self.cmd)
        return self.process

    def __exit__(self, exc_type, exc_value, traceback):
        if self.process:
            self.process.terminate() # graceful shutdown
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Process did not terminate gracefully, sending SIGKILL.")

            self.process.kill() # force kill
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.error("Process did not respond to SIGKILL, may be a zombie process.")

            # Double-check process status
            if self.process.poll() is None:
                logger.warning("Process still running after kill attempts, forcing kill again.")
                self.process.kill()

        if self.log_file:
            self.log_file.close()

    def wait_login_panel_up(self, url: str, timeout: int) -> bool:
        sb = sb_cdp.Chrome(url=None, headless=True)
        sb.open(url)

        wait = 1
        while timeout > 0:
            sb.refresh()
            sb.sleep(wait)
            logger.info("Waiting for login panel at %s to come up.", url)

            if sb.is_element_present('input[type="password"]'):
                logger.info("Login panel is up at %s", url)
                sb.driver.stop()
                return True

            timeout -= wait
            wait = min(wait * 2, 10)  # exponential backoff up to 10 seconds

        sb.driver.stop()
        logger.error("Login panel did not come up at %s within %i seconds.", url, timeout)
        return False


class RunDockerCompose(StartupScript):
    """Run a docker compose file from the test-network directory and wait for a port to respond."""

    def __init__(self, compose_file_path: str, wait_for_login_url, timeout: int = 600, log_path: Path | None = None):
        self.compose_file_path = self.find_docker_compose_file(compose_file_path)

        logger.info("Starting docker compose %s", self.compose_file_path)
        super().__init__(
            cmd=["docker", "compose", "-f", self.compose_file_path ,"up"],
            cwd=self.compose_file_path.parent,
            wait_for_login_url=wait_for_login_url,
            timeout=timeout,
            log_path=log_path
        )

    def find_docker_compose_file(self, compose_file_path: str) -> Path:
        full_path = Path(__file__).parent / "test-network" / compose_file_path

        if full_path.suffix == ".yaml" or full_path.suffix == ".yml":
            return full_path
        else:
            for file in full_path.iterdir():
                if file.name in ("docker-compose.yaml", "docker-compose.yml"):
                    return file
            raise FileNotFoundError(f"No docker-compose.yaml or docker-compose.yml found in {full_path}")


    def __exit__(self, exc_type, exc_value, traceback):
        logger.info("Stopping docker compose %s", self.compose_file_path)

        super().__exit__(exc_type, exc_value, traceback) # kills the docker compose up process

        if not self.docker_compose_down() and not self.docker_compose_force_kill():
            logger.error("Failed to stop docker compose services for %s", self.compose_file_path)
 
    def docker_compose_down(self) -> bool:
        try:
            down_proc = subprocess.Popen(
                ["docker", "compose", "-f", self.compose_file_path, "down", "-v", "--remove-orphans"],
                cwd=self.compose_file_path.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            down_proc.wait(timeout=10)
            return True
        except subprocess.TimeoutExpired:
            logger.warning("docker compose down timed out for %s; Trying to force-kill containers.", self.compose_file_path)
            return False

    def docker_compose_force_kill(self) -> bool:
        try:
            kill_proc = subprocess.Popen(
                ["docker", "compose", "-f", self.compose_file_path, "kill"],
                cwd=self.compose_file_path.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            kill_proc.wait(timeout=10)
            return True
        except subprocess.TimeoutExpired:
            logger.warning("docker compose kill timed out for %s; terminating kill process.", self.compose_file_path)
            return False
