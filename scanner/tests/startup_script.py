import subprocess
import logging
import time
import os
import requests
from pathlib import Path
import threading


class StartupScript:
    """
    Helper class for tests to automatically deploy an app using a startup script from apps/
    Implements the context manager protocol to start and stop the script.
    """

    def __init__(self, cmd: list[str], wait_for_port: int, timeout: int = 30, cwd="/tmp"):
        self.cmd = cmd
        self.cwd = cwd
        self.wait_for_port = wait_for_port
        self.process = None
        self.timeout = timeout

    def __enter__(self):
        def stream_logs(process):
            for line in process.stdout:
                print(line, end='')

        subprocess.run(["sudo", "docker", "container", "prune", "-f"], check=True)
        subprocess.run(["sudo", "docker", "network", "prune", "-f"], check=True)

        self.process = subprocess.Popen(
            self.cmd,
            cwd=self.cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
        )

        threading.Thread(target=stream_logs, args=(self.process,), daemon=True).start()

        start_time = time.time()
        last_log_time = 0.0
        while True:
            try:
                response = requests.get(f"http://localhost:{self.wait_for_port}", timeout=10)
                if response.status_code < 400:
                    break
            except requests.RequestException as exc:
                now = time.time()
                if now - last_log_time >= 10:
                    logging.debug(
                        "Waiting for port %s: %s",
                        self.wait_for_port,
                        str(exc)
                    )
                    last_log_time = now

            if time.time() - start_time > self.timeout:
                raise TimeoutError(f"Timeout reached while waiting for port {self.wait_for_port} to respond.")
            time.sleep(1)

        logging.info("Startup command %s ran successfully.", self.cmd)
        return self.process

    def __exit__(self, exc_type, exc_value, traceback):
        if self.process:
            self.process.kill()


class RunDockerCompose(StartupScript):
    """Run a docker compose file from the test-network directory and wait for a port to respond."""

    def __init__(self, compose_file_path: str, wait_for_port, timeout: int = 600):
        full_path = Path(__file__).parent / "test-network" / compose_file_path
        compose_file_name = full_path.name if (full_path.suffix == ".yaml" or full_path.suffix == ".yml") else "docker-compose.yml"

        logger = logging.getLogger('scanner.tests.startup_script')
        logger.info("Starting docker compose from %s", full_path)

        super().__init__(
            cmd=["docker", "compose", "-f", compose_file_name, "up", "--abort-on-container-exit"],
            cwd=full_path.parent,
            wait_for_port=wait_for_port,
            timeout=timeout
        )
        self.compose_file_name = compose_file_name

    def __exit__(self, exc_type, exc_value, traceback):
        logger = logging.getLogger('scanner.tests.startup_script')
        logger.info("Stopping docker compose from %s", self.compose_file_name)

        super().__exit__(exc_type, exc_value, traceback)
        try:
            down_proc = subprocess.Popen(
                ["docker", "compose", "-f", self.compose_file_name, "down", "--timeout", "30"],
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            down_proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            logger.warning("docker compose down timed out for %s; terminating down process and force-killing containers.", self.compose_file_name)
            try:
                down_proc.terminate()
                down_proc.communicate(timeout=10)
            except Exception:
                down_proc.kill()
            try:
                subprocess.run(
                    ["docker", "compose", "-f", self.compose_file_name, "kill"],
                    cwd=self.cwd,
                    check=False,
                    timeout=30
                )
                subprocess.run(
                    ["docker", "compose", "-f", self.compose_file_name, "down", "--remove-orphans"],
                    cwd=self.cwd,
                    check=False,
                    timeout=30
                )
            except subprocess.TimeoutExpired:
                logger.warning("docker compose kill/down timed out for %s; giving up.", self.compose_file_name)
