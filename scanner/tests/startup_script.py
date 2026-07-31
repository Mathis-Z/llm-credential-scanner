# Test helpers for deploying applications via subprocess or docker-compose.

import subprocess
import logging
import time
import threading
from pathlib import Path
from seleniumbase import SB

logger = logging.getLogger('scanner.tests.startup_script')


class StartupScript:
    """
    Context manager for running arbitrary startup commands in tests.
    
    Starts the process, waits for a login panel to be accessible,
    and cleans up the process on exit.
    """

    def __init__(self, cmd: list[str], wait_for_login_url: int, timeout: int = 240, cwd="/tmp", log_path: Path | None = None):
        self.cmd = cmd
        self.cwd = cwd
        self.wait_for_login_url = wait_for_login_url
        self.process = None
        self.timeout = timeout
        self.log_path = log_path
        self.log_file = None
        self.log_thread = None

    def __enter__(self):
        def stream_logs(process, log_file):
            """Stream process output to file or stdout."""
            for line in process.stdout:
                try:
                    if log_file:
                        log_file.write(line)
                        log_file.flush()
                    else:
                        print(line, end='')
                except ValueError:
                    break

        # Clean up Docker before starting
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

        self.log_thread = threading.Thread(target=stream_logs, args=(self.process, self.log_file), daemon=True)
        self.log_thread.start()

        if not self.wait_login_panel_up(self.wait_for_login_url, timeout=self.timeout):
            self.cleanup_process()
            raise TimeoutError(f"Timeout reached while waiting for login panel {self.wait_for_login_url} to come up.")

        logger.info("Startup command %s ran successfully.", self.cmd)
        return self.process

    def __exit__(self, exc_type, exc_value, traceback):
        self.cleanup_process()

    def cleanup_process(self):
        """Gracefully terminate process, then force kill if necessary."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Process did not terminate gracefully, sending SIGKILL.")

            self.process.kill()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.error("Process did not respond to SIGKILL, may be a zombie process.")

            if self.process.poll() is None:
                logger.warning("Process still running after kill attempts, forcing kill again.")
                self.process.kill()

        if self.log_thread:
            self.log_thread.join(timeout=5)

        if self.log_file:
            self.log_file.close()

    def wait_login_panel_up(self, url: str, timeout: int) -> bool:
        """
        Poll URL until password input element is present or timeout expires.
        
        Uses exponential backoff between retries.
        """
        try:
            with SB(uc=True, headless=True, chromium_arg="--disable-dev-shm-usage") as sb:
                wait = 1
                while timeout > 0:
                    sb.open(url)
                    sb.sleep(wait)
                    logger.info("Waiting for login panel at %s to come up.", url)

                    if sb.is_element_present('input[type="password"]'):
                        logger.info("Login panel is up at %s", url)
                        time.sleep(5)  # Allow time for service to be fully ready
                        return True

                    timeout -= wait
                    wait = min(wait * 2, 10)  # exponential backoff

                html = sb.get_page_source()
                logger.error("Login panel did not come up at %s within %i seconds.", url, timeout)
                logger.debug("Final page source at %s:\n%s", url, html)
                return False
        except Exception as e:
            logger.error("Error waiting for login panel at %s: %s", url, e)
            return False


class RunDockerCompose(StartupScript):
    """Run a docker compose file from a test network directory and wait for a port to respond."""

    def __init__(self, compose_file_path: str, wait_for_login_url, timeout: int = 240, log_path: Path | None = None, network_dir: str = "test-network"):
        self.network_dir = network_dir
        self.compose_file_path = self.find_docker_compose_file(compose_file_path)

        logger.info("Starting docker compose %s", self.compose_file_path)
        super().__init__(
            cmd=["docker", "compose", "-f", self.compose_file_path, "up"],
            cwd=self.compose_file_path.parent,
            wait_for_login_url=wait_for_login_url,
            timeout=timeout,
            log_path=log_path
        )

    def find_docker_compose_file(self, compose_file_path: str) -> Path:
        """Locate docker-compose.yaml file relative to self.network_dir directory."""
        full_path = Path(__file__).parent / self.network_dir / compose_file_path

        if full_path.suffix in (".yaml", ".yml"):
            return full_path
        else:
            # Assume it's a directory name; look for docker-compose.yaml inside
            for file in full_path.iterdir():
                if file.name in ("docker-compose.yaml", "docker-compose.yml"):
                    return file
            raise FileNotFoundError(f"No docker-compose.yaml or docker-compose.yml found in {full_path}")

    def __enter__(self):
        try:
            return super().__enter__()
        except Exception as e:
            self.cleanup()
            raise e

    def __exit__(self, exc_type, exc_value, traceback):
        logger.info("Stopping docker compose %s", self.compose_file_path)
        super().__exit__(exc_type, exc_value, traceback)
        self.cleanup()

    def cleanup(self):
        """Stop docker-compose services, force kill if graceful shutdown fails."""
        if not self.docker_compose_down() and not self.docker_compose_force_kill():
            logger.error("Failed to stop docker compose services for %s", self.compose_file_path)

    def docker_compose_down(self) -> bool:
        """Gracefully stop services and remove containers."""
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
            logger.warning("docker compose down timed out; trying force kill.")
            return False

    def docker_compose_force_kill(self) -> bool:
        """Force kill all containers managed by this compose file."""
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
            logger.warning("docker compose kill timed out.")
            return False
